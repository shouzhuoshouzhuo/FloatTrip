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

    uid = str(uuid.uuid4())
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
