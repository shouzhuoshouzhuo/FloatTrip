"""行程手动编辑 API 测试：search_city_pois / poi 搜索代理 / PUT timeline 保存。"""

from __future__ import annotations

import urllib.parse
import uuid

import pytest
from fastapi.testclient import TestClient


# ─── search_city_pois ────────────────────────────────────────

class TestSearchCityPois:
    def test_传入类型与关键词并解析结果(self, monkeypatch):
        from app.providers.amap import poi as poi_mod

        captured = {}

        def fake_get(url):
            captured["url"] = url
            return {"status": "1", "pois": [{"name": "颐和路", "location": "118.77,32.06"}]}

        monkeypatch.setattr(poi_mod, "http_get_json", fake_get)
        out = poi_mod.search_city_pois("南京", "k", keywords="颐和路", types="风景名胜", offset=8)
        assert out == [{"name": "颐和路", "location": "118.77,32.06"}]

        # 用 parse_qs 解析 URL query string
        parsed_url = urllib.parse.urlparse(captured["url"])
        query_params = urllib.parse.parse_qs(parsed_url.query)
        assert query_params["keywords"] == ["颐和路"]
        assert query_params["types"] == ["风景名胜"]
        assert query_params["citylimit"] == ["true"]
        assert query_params["offset"] == ["8"]

    def test_接口失败抛RuntimeError(self, monkeypatch):
        from app.providers.amap import poi as poi_mod

        monkeypatch.setattr(poi_mod, "http_get_json", lambda url: {"status": "0", "info": "INVALID_KEY"})
        with pytest.raises(RuntimeError, match="INVALID_KEY"):
            poi_mod.search_city_pois("南京", "k", keywords="x", types="餐饮服务")


# ─── API 路由测试基建 ────────────────────────────────────────

@pytest.fixture()
def client(tmp_path, monkeypatch):
    """隔离 SQLite 到临时目录，禁用 Redis 缓存。"""
    import app.core.database as database

    monkeypatch.setattr(database, "_DB_PATH", tmp_path / "test.db")
    database.init_db()

    import app.api.plan_routes as plan_routes
    monkeypatch.setattr(plan_routes, "get_cached", lambda key: None)
    monkeypatch.setattr(plan_routes, "set_cached", lambda key, value, ttl: None)

    from app.main import app
    return TestClient(app)


def make_auth():
    """造一个用户 id + Bearer 头。"""
    from app.core.auth import create_token
    from app.core.database import get_conn

    uid = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,?)",
            (uid, f"test-{uid}", "test", "2026-01-01T00:00:00Z"),
        )
    return uid, {"Authorization": "Bearer " + create_token(uid)}


# ─── GET /api/poi/search ─────────────────────────────────────

class TestPoiSearch:
    def test_未登录返回401(self, client):
        r = client.get("/api/poi/search", params={"city": "南京", "kw": "颐和路"})
        assert r.status_code == 401

    def test_非法kind返回400(self, client):
        _, headers = make_auth()
        r = client.get("/api/poi/search", params={"city": "南京", "kw": "x", "kind": "hotel"}, headers=headers)
        assert r.status_code == 400

    def test_attraction分支走风景名胜并解析(self, client, monkeypatch):
        import app.api.plan_routes as plan_routes

        captured = {}

        def fake_search(city, key, *, keywords, types, offset):
            captured.update(city=city, keywords=keywords, types=types)
            return [{
                "name": "颐和路历史街区", "location": "118.77,32.06",
                "biz_ext": {"rating": "4.7", "opentime2": "全天"},
                "address": "鼓楼区颐和路", "photos": [],
            }]

        monkeypatch.setattr(plan_routes, "search_city_pois", fake_search)
        monkeypatch.setattr(plan_routes, "amap_key", lambda: "fake-key")

        _, headers = make_auth()
        r = client.get("/api/poi/search", params={"city": "南京", "kw": "颐和路"}, headers=headers)
        assert r.status_code == 200
        assert captured["types"] == "风景名胜"
        results = r.json()["results"]
        assert results[0]["name"] == "颐和路历史街区"
        assert results[0]["rating"] == 4.7
        assert results[0]["address"] == "鼓楼区颐和路"
        assert results[0]["location"] == {"lng": 118.77, "lat": 32.06}

    def test_restaurant分支走餐饮服务(self, client, monkeypatch):
        import app.api.plan_routes as plan_routes

        captured = {}

        def fake_search(city, key, *, keywords, types, offset):
            captured["types"] = types
            return [{
                "name": "南京大牌档", "location": "118.78,32.04", "type": "餐饮服务;中餐厅",
                "biz_ext": {"rating": "4.6", "cost": "80"}, "address": "秦淮区贡院街", "photos": [],
            }]

        monkeypatch.setattr(plan_routes, "search_city_pois", fake_search)
        monkeypatch.setattr(plan_routes, "amap_key", lambda: "fake-key")

        _, headers = make_auth()
        r = client.get("/api/poi/search", params={"city": "南京", "kw": "大牌档", "kind": "restaurant"}, headers=headers)
        assert r.status_code == 200
        assert captured["types"] == "餐饮服务"
        results = r.json()["results"]
        assert results[0]["cost"] == "80"

    def test_高德失败返回502(self, client, monkeypatch):
        import app.api.plan_routes as plan_routes

        def boom(city, key, *, keywords, types, offset):
            raise RuntimeError("高德搜索失败：QUOTA")

        monkeypatch.setattr(plan_routes, "search_city_pois", boom)
        monkeypatch.setattr(plan_routes, "amap_key", lambda: "fake-key")

        _, headers = make_auth()
        r = client.get("/api/poi/search", params={"city": "南京", "kw": "x"}, headers=headers)
        assert r.status_code == 502

    def test_缓存命中直接返回不调搜索(self, client, monkeypatch):
        import app.api.plan_routes as plan_routes

        called = []
        monkeypatch.setattr(plan_routes, "get_cached", lambda key: [{"name": "缓存景点"}])
        monkeypatch.setattr(plan_routes, "search_city_pois",
                            lambda *a, **k: called.append(1))

        _, headers = make_auth()
        r = client.get("/api/poi/search", params={"city": "南京", "kw": "x"}, headers=headers)
        assert r.status_code == 200
        assert r.json()["results"] == [{"name": "缓存景点"}]
        assert not called

    def test_超长kw返回400(self, client):
        _, headers = make_auth()
        r = client.get("/api/poi/search", params={"city": "南京", "kw": "x" * 101}, headers=headers)
        assert r.status_code == 400


# ─── PUT /api/plan/{plan_id}/timeline ────────────────────────

def make_plan(uid: str) -> str:
    """直接落库一份两景点一餐厅的最小行程，返回 plan_id。"""
    from app.core.database import get_conn
    from app.core.memory import save_itinerary

    plan = {
        "destination": "南京", "start_date": "2026-06-10", "end_date": "2026-06-10",
        "days_count": 1,
        "days": [{
            "day": 1, "date": "2026-06-10", "theme": "古迹",
            "timeline": [
                {"type": "attraction", "name": "中山陵", "start_time": "09:00", "end_time": "11:30",
                 "period": "morning", "location": {"lat": 32.058, "lng": 118.848}},
                {"type": "lunch", "name": "老门东小吃", "location": {"lat": 32.02, "lng": 118.79}},
                {"type": "attraction", "name": "夫子庙", "start_time": "14:00", "end_time": "17:00",
                 "period": "afternoon", "location": {"lat": 32.021, "lng": 118.788}},
            ],
        }],
    }
    with get_conn() as conn:
        return save_itinerary(uid, plan, "测试查询", conn)


class TestSaveTimeline:
    def test_未登录401(self, client):
        r = client.put("/api/plan/x/timeline", json={"days": []})
        assert r.status_code == 401

    def test_行程不存在404(self, client):
        _, headers = make_auth()
        r = client.put("/api/plan/不存在/timeline", json={"days": []}, headers=headers)
        assert r.status_code == 404

    def test_他人行程403(self, client):
        owner, _ = make_auth()
        pid = make_plan(owner)
        _, other_headers = make_auth()
        r = client.put(f"/api/plan/{pid}/timeline", json={"days": []}, headers=other_headers)
        assert r.status_code == 403

    def test_day越界400(self, client):
        uid, headers = make_auth()
        pid = make_plan(uid)
        r = client.put(f"/api/plan/{pid}/timeline",
                       json={"days": [{"day": 9, "timeline": []}]}, headers=headers)
        assert r.status_code == 400

    def test_缺type条目422(self, client):
        uid, headers = make_auth()
        pid = make_plan(uid)
        r = client.put(f"/api/plan/{pid}/timeline",
                       json={"days": [{"day": 1, "timeline": [{"name": "无类型"}]}]}, headers=headers)
        assert r.status_code == 422

    def test_景点缺name422(self, client):
        uid, headers = make_auth()
        pid = make_plan(uid)
        r = client.put(f"/api/plan/{pid}/timeline",
                       json={"days": [{"day": 1, "timeline": [{"type": "attraction"}]}]}, headers=headers)
        assert r.status_code == 422

    def test_保存成功_服务端重算距离_持久化(self, client):
        from app.core.database import get_conn
        from app.core.memory import load_itinerary
        from app.planning.helpers import haversine_km

        uid, headers = make_auth()
        pid = make_plan(uid)

        # 交换两景点顺序，并故意传入伪造的距离值
        new_timeline = [
            {"type": "attraction", "name": "夫子庙", "start_time": "09:00", "end_time": "11:30",
             "period": "morning", "location": {"lat": 32.021, "lng": 118.788},
             "dist_from_prev_km": 999},
            {"type": "lunch", "name": "老门东小吃", "location": {"lat": 32.02, "lng": 118.79},
             "dist_from_prev_km": 999},
            {"type": "attraction", "name": "中山陵", "start_time": "14:00", "end_time": "17:00",
             "period": "afternoon", "location": {"lat": 32.058, "lng": 118.848}},
        ]
        r = client.put(f"/api/plan/{pid}/timeline",
                       json={"days": [{"day": 1, "timeline": new_timeline}]}, headers=headers)
        assert r.status_code == 200

        saved = r.json()["plan"]["days"][0]["timeline"]
        assert [it["name"] for it in saved] == ["夫子庙", "老门东小吃", "中山陵"]
        # 首条无距离；其余距离 = 服务端 haversine 重算（伪造的 999 被丢弃）
        assert "dist_from_prev_km" not in saved[0]
        expect = round(haversine_km({"lat": 32.021, "lng": 118.788}, {"lat": 32.02, "lng": 118.79}), 2)
        assert saved[1]["dist_from_prev_km"] == expect

        # 已持久化：重新加载与响应一致
        with get_conn() as conn:
            reloaded = load_itinerary(pid, conn)["plan"]
        assert reloaded["days"][0]["timeline"] == saved

    def test_残缺location不致500(self, client):
        uid, headers = make_auth()
        pid = make_plan(uid)
        r = client.put(f"/api/plan/{pid}/timeline", json={"days": [{"day": 1, "timeline": [
            {"type": "attraction", "name": "A", "location": {"lng": 118.0}},
            {"type": "attraction", "name": "B", "location": {"lat": 32.0, "lng": 118.8}},
        ]}]}, headers=headers)
        assert r.status_code == 200
        saved = r.json()["plan"]["days"][0]["timeline"]
        assert "dist_from_prev_km" not in saved[1]  # 前一条坐标残缺，不算距离
