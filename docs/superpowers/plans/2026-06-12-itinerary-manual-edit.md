# 行程手动编辑（拖拽换序 / 更换景点 / 改时间）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在行程详情页提供显式编辑模式：拖拽换序（SortableJS）、搜索更换/新增景点和餐厅、删除、编辑时间段、逐步撤销/重做，点「完成编辑」一次性持久化。

**Architecture:** 编辑过程全部在前端内存（draft + 快照撤销栈）完成；后端只新增两个接口——`GET /api/poi/search`（高德搜索代理，Key 不出服务端）和 `PUT /api/plan/{plan_id}/timeline`（只合并 timeline 进 plan_json，服务端重算距离，复用 `update_plan_json` 原地更新，不产生新 plan_id）。

**Tech Stack:** FastAPI + SQLite（现有）、SortableJS 1.15（CDN）、React 18 无构建 JSX（现有）、pytest + TestClient（后端测试）。

**设计文档：** `docs/superpowers/specs/2026-06-12-itinerary-manual-edit-design.md`（需求决策表以它为准）

**项目背景速览（给零上下文的执行者）：**
- 启动：`python run.py`（http://localhost:8765）；后端测试：`python -m pytest tests/test_manual_edit_api.py -v`
- 行程数据结构：`plan_json.days[] = {day, date, theme, timeline[]}`；timeline 条目两类：
  - 景点 `{type:"attraction", name, start_time, end_time, period, rating, open_time, photo, location:{lat,lng}, tip, dist_from_prev_km}`
  - 餐厅 `{type:"lunch"|"dinner", name, rating, cost, address, photo, location, reason, no_restaurant?, dist_from_prev_km}`
- 前端无构建：JSX 文件经 Babel Standalone 浏览器端转译，组件通过 `Object.assign(window, {...})` 共享，**没有 import/export**
- 注释、UI 文案一律中文

---

### Task 1: 后端 — 通用城市 POI 文本搜索函数 `search_city_pois`

现有 `search_attraction_pois` 把类型硬编码为风景名胜且自带缓存，手动搜索需要类型可指定（景点/餐饮）的通用版本，缓存交给调用方。

**Files:**
- Modify: `app/providers/amap/poi.py`（在 `search_attraction_pois` 之后追加）
- Test: `tests/test_manual_edit_api.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_manual_edit_api.py`：

```python
"""行程手动编辑 API 测试：search_city_pois / poi 搜索代理 / PUT timeline 保存。"""

from __future__ import annotations

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
        assert "citylimit=true" in captured["url"]
        assert "offset=8" in captured["url"]

    def test_接口失败抛RuntimeError(self, monkeypatch):
        from app.providers.amap import poi as poi_mod

        monkeypatch.setattr(poi_mod, "http_get_json", lambda url: {"status": "0", "info": "INVALID_KEY"})
        with pytest.raises(RuntimeError, match="INVALID_KEY"):
            poi_mod.search_city_pois("南京", "k", keywords="x", types="餐饮服务")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_manual_edit_api.py -v`
Expected: FAIL，`AttributeError: ... has no attribute 'search_city_pois'`

- [ ] **Step 3: 实现 `search_city_pois`**

在 `app/providers/amap/poi.py` 的 `search_attraction_pois` 函数之后追加：

```python
def search_city_pois(
    city: str,
    api_key: str,
    *,
    keywords: str,
    types: str,
    offset: int = 8,
) -> list[dict[str, Any]]:
    """通用城市关键字搜索（手动编辑换点用）：类型可指定（景点/餐饮），不做缓存（由调用方决定）。"""
    params: dict[str, str] = {
        "key": api_key,
        "keywords": keywords,
        "types": types,
        "city": city,
        "citylimit": "true",
        "offset": str(offset),
        "page": "1",
        "extensions": "all",
        "output": "json",
    }
    url = f"{AMAP_TEXT_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    for attempt in range(4):
        data = http_get_json(url)
        if data.get("status") == "1":
            pois = data.get("pois", [])
            return pois if isinstance(pois, list) else []
        info = str(data.get("info") or "未知错误")
        if info not in AMAP_RATE_LIMIT_INFOS or attempt >= 3:
            raise RuntimeError(f"高德搜索失败：{info}")
        time.sleep(1.2 * (attempt + 1))
    return []
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_manual_edit_api.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add app/providers/amap/poi.py tests/test_manual_edit_api.py
git commit -m "feat(amap): 新增 search_city_pois 通用城市文本搜索（手动换点用）"
```

---

### Task 2: 后端 — `GET /api/poi/search` 搜索代理路由

**Files:**
- Modify: `app/api/plan_routes.py`（文件末尾追加路由；顶部补 import）
- Test: `tests/test_manual_edit_api.py`（追加）

- [ ] **Step 1: 在测试文件追加 fixture 与测试**

在 `tests/test_manual_edit_api.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_manual_edit_api.py -v`
Expected: TestPoiSearch 全部 FAIL（404，路由不存在）；TestSearchCityPois 仍 PASS

- [ ] **Step 3: 实现路由**

`app/api/plan_routes.py` 顶部 import 区追加：

```python
from app.core.cache import POI_TTL, get_cached, poi_cache_key, set_cached
from app.planning.helpers import amap_key, restaurant_to_dict
from app.providers.amap.poi import (
    ATTRACTION_TYPE,
    normalize_address,
    poi_to_spot,
    search_city_pois,
)
```

（`haversine_km` 已在现有 import 中。）文件末尾追加：

```python
# ─── 手动编辑：POI 搜索代理 ──────────────────────────────────


@router.get("/api/poi/search")
def poi_search(
    city: str,
    kw: str,
    kind: str = "attraction",
    authorization: str | None = Header(default=None),
):
    """手动换点/加点的搜索代理：高德 Key 不出服务端，结果走 Redis 缓存。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="需要登录")
    if not decode_token(authorization[7:]):
        raise HTTPException(status_code=401, detail="token 无效或已过期")
    if kind not in ("attraction", "restaurant"):
        raise HTTPException(status_code=400, detail="kind 须为 attraction 或 restaurant")

    cache_key = poi_cache_key(city, f"manual:{kind}:{kw}")
    cached = get_cached(cache_key)
    if cached is not None:
        return {"results": cached}

    types = ATTRACTION_TYPE if kind == "attraction" else "餐饮服务"
    try:
        raw = search_city_pois(city, amap_key(), keywords=kw, types=types, offset=8)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    results: list[dict] = []
    for poi in raw:
        parsed = poi_to_spot(poi) if kind == "attraction" else restaurant_to_dict(poi)
        if not parsed:
            continue
        if kind == "attraction":
            # poi_to_spot 不含地址，搜索结果需要地址帮用户分辨同名地点
            parsed["address"] = normalize_address(poi.get("address"))
        results.append(parsed)
    results = results[:8]

    set_cached(cache_key, results, POI_TTL)
    return {"results": results}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_manual_edit_api.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add app/api/plan_routes.py tests/test_manual_edit_api.py
git commit -m "feat(api): 新增 /api/poi/search 高德搜索代理（手动换景点/餐厅用）"
```

---

### Task 3: 后端 — `PUT /api/plan/{plan_id}/timeline` 保存路由

**Files:**
- Modify: `app/api/plan_routes.py`（末尾追加）
- Test: `tests/test_manual_edit_api.py`（追加）

- [ ] **Step 1: 追加测试**

在 `tests/test_manual_edit_api.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_manual_edit_api.py -v -k SaveTimeline`
Expected: 除 401 外全部 FAIL（405/404，路由不存在）

注意：FastAPI 对不存在的 PUT 路径返回 405/404 而不是 401，`test_未登录401` 此时也会 FAIL——这是预期的。

- [ ] **Step 3: 实现路由**

`app/api/plan_routes.py` 末尾追加：

```python
# ─── 手动编辑：保存逐天 timeline ─────────────────────────────


def _recalc_dists(timeline: list[dict]) -> None:
    """服务端重算相邻条目距离，不信任前端传入的 dist_from_prev_km。"""
    for i, item in enumerate(timeline):
        if i == 0:
            item.pop("dist_from_prev_km", None)
            continue
        prev_loc = timeline[i - 1].get("location")
        cur_loc = item.get("location")
        if prev_loc and cur_loc:
            item["dist_from_prev_km"] = round(haversine_km(prev_loc, cur_loc), 2)
        else:
            item.pop("dist_from_prev_km", None)


class TimelineDayPayload(BaseModel):
    day: int                  # 1-based
    timeline: list[dict]


class SaveTimelineRequest(BaseModel):
    days: list[TimelineDayPayload]


@router.put("/api/plan/{plan_id}/timeline")
def save_timeline(
    plan_id: str,
    req: SaveTimelineRequest,
    authorization: str | None = Header(default=None),
):
    """保存手动编辑后的逐天 timeline。只合并 timeline，不允许前端覆盖 plan 其他字段。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="需要登录")
    user_id = decode_token(authorization[7:])
    if not user_id:
        raise HTTPException(status_code=401, detail="token 无效或已过期")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM itineraries WHERE id=?", (plan_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="行程不存在")
        if row["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="无权访问")
        data = load_itinerary(plan_id, conn)

    plan = data["plan"]
    day_by_no = {d.get("day"): d for d in plan.get("days", [])}
    for payload in req.days:
        day_obj = day_by_no.get(payload.day)
        if not day_obj:
            raise HTTPException(status_code=400, detail=f"第 {payload.day} 天不存在")
        for item in payload.timeline:
            if not isinstance(item, dict) or not item.get("type"):
                raise HTTPException(status_code=422, detail="timeline 条目缺少 type")
            if item["type"] == "attraction" and not item.get("name"):
                raise HTTPException(status_code=422, detail="景点条目缺少 name")
        _recalc_dists(payload.timeline)
        day_obj["timeline"] = payload.timeline

    with get_conn() as conn:
        ok = update_plan_json(plan_id, user_id, plan, conn)
    if not ok:
        raise HTTPException(status_code=500, detail="保存失败")

    return {"plan": plan}
```

- [ ] **Step 4: 运行全部测试确认通过**

Run: `python -m pytest tests/test_manual_edit_api.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add app/api/plan_routes.py tests/test_manual_edit_api.py
git commit -m "feat(api): 新增 PUT /api/plan/{id}/timeline 手动编辑保存（服务端重算距离）"
```

---

### Task 4: 前端基建 — SortableJS CDN + api.js 客户端函数 + edit.jsx 挂载

**Files:**
- Modify: `frontend/index.html:18`（Babel script 之后加 SortableJS；组件脚本区加 edit.jsx）
- Modify: `frontend/api.js`（`revertDay` 之后追加两个函数 + 导出）
- Create: `frontend/edit.jsx`（先占位，Task 5 填充）

- [ ] **Step 1: index.html 加脚本**

Babel 那行（`@babel/standalone`）之后追加：

```html
  <!-- SortableJS（行程手动编辑拖拽） -->
  <script src="https://unpkg.com/sortablejs@1.15.6/Sortable.min.js" crossorigin></script>
```

组件脚本区，在 `components.jsx` 与 `pages.jsx` 之间插入：

```html
  <script type="text/babel" src="/edit.jsx"></script>
```

- [ ] **Step 2: api.js 追加客户端函数**

在 `revertDay` 函数之后追加：

```js
/* ── 手动编辑 ─────────────────────────────────────── */
async function searchPoi(city, kw, kind) {
  const qs = new URLSearchParams({ city, kw, kind });
  const r = await fetch(`/api/poi/search?${qs}`, { headers: authHeaders() });
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || "搜索失败"); }
  return (await r.json()).results || [];
}

async function saveTimeline(plan_id, days) {
  const r = await fetch(`/api/plan/${encodeURIComponent(plan_id)}/timeline`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ days }),
  });
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || "保存失败"); }
  return r.json();
}
```

文件底部 `Object.assign(window, {...})` 里追加 `searchPoi, saveTimeline,`（加在 `optimizeDay, revertDay,` 之后）。

- [ ] **Step 3: 创建 edit.jsx 占位**

新建 `frontend/edit.jsx`：

```jsx
// edit.jsx — 行程手动编辑：编辑态时间轴 / 拖拽 / 搜索弹层 / 时间编辑（Task 5 填充）
```

- [ ] **Step 4: 验证页面无报错**

启动 `python run.py`，打开 http://localhost:8765 ，确认控制台无新增报错、`window.Sortable` 与 `window.searchPoi` 已定义（DevTools console 输入验证）。

- [ ] **Step 5: 提交**

```bash
git add frontend/index.html frontend/api.js frontend/edit.jsx
git commit -m "feat(frontend): 手动编辑基建——SortableJS CDN、searchPoi/saveTimeline 客户端"
```

---

### Task 5: 前端 — edit.jsx 编辑组件全集

纯逻辑工具 + 搜索弹层 + 时间编辑器 + 编辑卡片 + 可拖拽时间轴 + 工具栏。全部挂到 window。

**Files:**
- Modify: `frontend/edit.jsx`（完整内容如下，覆盖占位）

- [ ] **Step 1: 写入完整 edit.jsx**

```jsx
// edit.jsx — 行程手动编辑：编辑态时间轴 / 拖拽 / 搜索弹层 / 时间编辑

/* ── 纯函数工具 ──────────────────────────────────── */

// 与后端 helpers.haversine_km 同公式；仅用于编辑态即时显示，落库以服务端重算为准
function haversineKm(a, b) {
  const R = 6371.0;
  const rad = (x) => (x * Math.PI) / 180;
  const dlat = rad(b.lat - a.lat), dlon = rad(b.lng - a.lng);
  const h = Math.sin(dlat / 2) ** 2 +
    Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dlon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

// 原地重算一天 timeline 的 dist_from_prev_km（规则与后端 _recalc_dists 一致）
function recalcDayDists(timeline) {
  timeline.forEach((item, i) => {
    if (i === 0) { delete item.dist_from_prev_km; return; }
    const prev = timeline[i - 1].location, cur = item.location;
    if (prev && cur) item.dist_from_prev_km = Math.round(haversineKm(prev, cur) * 100) / 100;
    else delete item.dist_from_prev_km;
  });
}

// 拖拽换序：时间段留在位置上不跟卡走——
// 先记录原顺序中各景点的时段，移动后按新顺序把时段逐个套回景点
function reorderKeepTimes(timeline, from, to) {
  const slots = timeline
    .filter(it => it.type === "attraction")
    .map(it => ({ start_time: it.start_time, end_time: it.end_time, period: it.period }));
  const arr = timeline.slice();
  const [moved] = arr.splice(from, 1);
  arr.splice(to, 0, moved);
  let si = 0;
  return arr.map(it => (it.type === "attraction" ? { ...it, ...slots[si++] } : it));
}

/* ── 搜索弹层（更换/新增 景点·餐厅） ───────────────── */
function PoiSearchModal({ city, kind, title, onPick, onClose }) {
  const [kw, setKw] = React.useState("");
  const [results, setResults] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [err, setErr] = React.useState("");

  const search = async () => {
    if (!kw.trim() || loading) return;
    setLoading(true); setErr("");
    try {
      const r = await searchPoi(city, kw.trim(), kind);
      setResults(r);
      if (!r.length) setErr("没找到，换个关键词试试");
    } catch (e) { setErr(e.message || "搜索失败"); }
    finally { setLoading(false); }
  };

  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-card poi-search-card">
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-title">{title}</div>
        <div className="poi-search-bar">
          <input className="form-input" autoFocus value={kw}
            placeholder={kind === "restaurant" ? "输入餐厅名或菜系，回车搜索" : "输入景点名，回车搜索"}
            onChange={(e) => setKw(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()} />
          <button className="go-btn" onClick={search} disabled={loading || !kw.trim()}>
            {loading ? "搜索中…" : "搜索"}
          </button>
        </div>
        {err && <div className="poi-search-err">{err}</div>}
        <div className="poi-results">
          {(results || []).map((p, i) => (
            <button key={i} className="poi-result" onClick={() => onPick(p)}>
              <span className="poi-result-name">{p.name}</span>
              <span className="poi-result-meta">
                {p.rating != null && <span>★ {Number(p.rating).toFixed(1)}</span>}
                {p.cost && <span>¥{p.cost}/人</span>}
                {p.open_time && <span>开放 {p.open_time}</span>}
                {p.address && <span>{p.address}</span>}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── 时间段编辑器（仅景点） ─────────────────────────── */
function TimeRangeEditor({ start, end, onCommit }) {
  const [st, setSt] = React.useState(start || "");
  const [et, setEt] = React.useState(end || "");
  const [bad, setBad] = React.useState(false);

  // 撤销/重做会改变传入的时间，同步回本地输入
  React.useEffect(() => { setSt(start || ""); setEt(end || ""); setBad(false); }, [start, end]);

  const commit = () => {
    if (st && et && st >= et) { setBad(true); return; }
    setBad(false);
    if (st !== (start || "") || et !== (end || "")) onCommit(st || null, et || null);
  };

  return (
    <span className={`time-edit ${bad ? "bad" : ""}`}>
      <input type="time" value={st} onChange={(e) => setSt(e.target.value)} onBlur={commit} />
      <span>–</span>
      <input type="time" value={et} onChange={(e) => setEt(e.target.value)} onBlur={commit} />
      {bad && <span className="time-edit-err">开始须早于结束</span>}
    </span>
  );
}

/* ── 编辑态卡片 ─────────────────────────────────────── */
function EditCard({ raw, dist, onReplace, onDelete, onTimeChange }) {
  const isAttr = raw.type === "attraction";
  const mealLabel = isAttr ? null : raw.type === "lunch" ? "午餐" : "晚餐";
  return (
    <div className="edit-card">
      <span className="drag-grip" title="拖拽调整顺序">⠿</span>
      <div className="edit-card-body">
        <div className="edit-card-title">
          <span>{raw.name || `${mealLabel || "条目"}（待安排）`}</span>
          {mealLabel && <span className="meal-flag">{mealLabel}</span>}
          {dist != null && dist > 0 && <span className="edit-dist">↕ {dist} km</span>}
        </div>
        <div className="edit-card-meta">
          {isAttr && <TimeRangeEditor start={raw.start_time} end={raw.end_time} onCommit={onTimeChange} />}
          {raw.rating != null && <span className="star">★ {Number(raw.rating).toFixed(1)}</span>}
          {!isAttr && raw.cost && <span>¥{raw.cost}/人</span>}
          {isAttr && raw.open_time && <span>开放 {raw.open_time}</span>}
        </div>
      </div>
      <div className="edit-card-acts">
        <button className="edit-act" onClick={onReplace}>↔ 更换</button>
        <button className="edit-act danger" onClick={onDelete} title="删除（可撤销）">✕</button>
      </div>
    </div>
  );
}

/* ── 可拖拽时间轴 ───────────────────────────────────── */
// ver：编辑版本号。每次 draft 变化 +1，靠 key 强制重挂载列表，
// 保证 Sortable 动过的 DOM 与 React state 重新对齐（SortableJS×React 标准做法）。
function EditableTimeline({ rawTimeline, ver, onReorder, onReplace, onDelete, onTimeChange, onAdd }) {
  const listRef = React.useRef(null);

  React.useEffect(() => {
    if (!listRef.current || !window.Sortable) return;
    const s = window.Sortable.create(listRef.current, {
      animation: 180,
      handle: ".drag-grip",
      ghostClass: "edit-ghost",
      onEnd: (evt) => {
        if (evt.oldIndex !== evt.newIndex) onReorder(evt.oldIndex, evt.newIndex);
      },
    });
    return () => s.destroy();
  }, [ver]); // eslint-disable-line

  return (
    <div className="edit-timeline">
      <div ref={listRef} key={ver} className="edit-list">
        {rawTimeline.map((raw, i) => (
          <EditCard key={`${ver}-${i}`} raw={raw} dist={raw.dist_from_prev_km}
            onReplace={() => onReplace(i)}
            onDelete={() => onDelete(i)}
            onTimeChange={(st, et) => onTimeChange(i, st, et)} />
        ))}
      </div>
      {rawTimeline.length === 0 && <div className="edit-empty">这一天还没有安排，用下面的按钮添加吧</div>}
      <div className="edit-add-row">
        <button className="edit-add" onClick={() => onAdd("attraction")}>＋ 景点</button>
        <button className="edit-add" onClick={() => onAdd("lunch")}>＋ 午餐</button>
        <button className="edit-add" onClick={() => onAdd("dinner")}>＋ 晚餐</button>
      </div>
    </div>
  );
}

/* ── 编辑工具栏 ─────────────────────────────────────── */
function EditToolbar({ canUndo, canRedo, saving, saveErr, onUndo, onRedo, onCancel, onSave }) {
  return (
    <div className="edit-toolbar">
      <button className="edit-tool" disabled={!canUndo} onClick={onUndo}>↩ 撤销</button>
      <button className="edit-tool" disabled={!canRedo} onClick={onRedo}>↪ 重做</button>
      <span className="edit-toolbar-hint">{saveErr ? "" : "拖动 ⠿ 调整顺序 · 点时间可修改"}</span>
      {saveErr && <span className="edit-save-err">{saveErr}</span>}
      <button className="edit-tool" onClick={onCancel}>✕ 取消</button>
      <button className="edit-tool primary" disabled={saving} onClick={onSave}>
        {saving ? "保存中…" : "✓ 完成编辑"}
      </button>
    </div>
  );
}

Object.assign(window, {
  haversineKm, recalcDayDists, reorderKeepTimes,
  PoiSearchModal, TimeRangeEditor, EditCard, EditableTimeline, EditToolbar,
});
```

- [ ] **Step 2: 验证转译无错**

刷新 http://localhost:8765 ，确认控制台无 Babel 语法错误、`window.EditableTimeline` 已定义。

- [ ] **Step 3: 提交**

```bash
git add frontend/edit.jsx
git commit -m "feat(frontend): 编辑组件全集——拖拽时间轴/搜索弹层/时间编辑/工具栏"
```

---

### Task 6: 前端 — TripDetailPage 接入编辑态

**Files:**
- Modify: `frontend/pages.jsx`（TripDetailPage 函数，约 289-465 行）

- [ ] **Step 1: 加编辑态 state 与处理函数**

在 TripDetailPage 现有 state 声明（`dayMsg` 之后）追加：

```jsx
  // ── 手动编辑态 ──
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(null);          // _raw.days 的深拷贝
  const [undoStack, setUndoStack] = React.useState([]);    // 元素 = draft 快照
  const [redoStack, setRedoStack] = React.useState([]);
  const [editVer, setEditVer] = React.useState(0);         // 每次变更 +1，驱动 Sortable 重挂载
  const [saving, setSaving] = React.useState(false);
  const [saveErr, setSaveErr] = React.useState("");
  // 搜索弹层目标：{ dayI, idx } 替换；{ dayI, idx:null, addType } 新增
  const [searchTarget, setSearchTarget] = React.useState(null);

  const dirty = undoStack.length > 0;

  // 编辑中刷新/关页守卫
  React.useEffect(() => {
    if (!editing || !dirty) return;
    const onBeforeUnload = (e) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [editing, dirty]);

  const enterEdit = () => {
    setDraft(structuredClone(plan._raw.days));
    setUndoStack([]); setRedoStack([]); setSaveErr("");
    setEditing(true); setEditVer(v => v + 1);
  };

  const exitEdit = () => {
    if (dirty && !confirm("放弃未保存的修改？")) return;
    setEditing(false); setDraft(null); setSaveErr("");
  };

  // 所有编辑操作的唯一入口：拷贝 → 变更 → 重算距离 → 压撤销栈
  const applyEdit = (mutate) => {
    setUndoStack(s => [...s, draft]);
    setRedoStack([]);
    const next = structuredClone(draft);
    mutate(next);
    next.forEach(d => recalcDayDists(d.timeline));
    setDraft(next); setEditVer(v => v + 1);
  };

  const undo = () => {
    if (!undoStack.length) return;
    setRedoStack(r => [...r, draft]);
    setDraft(undoStack[undoStack.length - 1]);
    setUndoStack(s => s.slice(0, -1));
    setEditVer(v => v + 1);
  };

  const redo = () => {
    if (!redoStack.length) return;
    setUndoStack(s => [...s, draft]);
    setDraft(redoStack[redoStack.length - 1]);
    setRedoStack(r => r.slice(0, -1));
    setEditVer(v => v + 1);
  };

  const saveEdit = async () => {
    setSaving(true); setSaveErr("");
    try {
      const days = draft.map((d, i) => ({ day: d.day ?? i + 1, timeline: d.timeline }));
      const res = await saveTimeline(planId, days);
      const adapted = adaptPlan(res.plan, currentUsername);
      adapted.logs = plan.logs;
      setPlan(adapted);
      setEditing(false); setDraft(null);
      setOptimizedDays({});   // 手动编辑后旧的"优化前快照"失效
    } catch (e) {
      setSaveErr(e.message || "保存失败，请重试");
    } finally { setSaving(false); }
  };

  // ── 各编辑操作 ──
  const handleReorder = (from, to) =>
    applyEdit(d => { d[dayIdx].timeline = reorderKeepTimes(d[dayIdx].timeline, from, to); });

  const handleDelete = (idx) =>
    applyEdit(d => { d[dayIdx].timeline.splice(idx, 1); });

  const handleTimeChange = (idx, st, et) =>
    applyEdit(d => { Object.assign(d[dayIdx].timeline[idx], { start_time: st, end_time: et }); });

  const handlePoiPick = (poi) => {
    const { idx, addType } = searchTarget;
    setSearchTarget(null);
    applyEdit(d => {
      const tl = d[dayIdx].timeline;
      if (idx != null) {
        const old = tl[idx];
        if (old.type === "attraction") {
          // 继承时间段与时段，其余字段来自新 POI；旧贴士不再适用
          tl[idx] = { ...old, name: poi.name, rating: poi.rating ?? null,
            open_time: poi.open_time ?? null, location: poi.location,
            photo: poi.photo ?? null, tip: null };
        } else {
          tl[idx] = { type: old.type, name: poi.name, rating: poi.rating ?? null,
            cost: poi.cost ?? null, address: poi.address ?? null,
            location: poi.location, photo: poi.photo ?? null,
            reason: null, no_restaurant: false };
        }
      } else if (addType === "attraction") {
        tl.push({ type: "attraction", name: poi.name, rating: poi.rating ?? null,
          open_time: poi.open_time ?? null, location: poi.location,
          photo: poi.photo ?? null, tip: null,
          start_time: null, end_time: null, period: "afternoon" });
      } else {
        tl.push({ type: addType, name: poi.name, rating: poi.rating ?? null,
          cost: poi.cost ?? null, address: poi.address ?? null,
          location: poi.location, photo: poi.photo ?? null,
          reason: null, no_restaurant: false });
      }
    });
  };

  // 编辑态视图：draft 经 adaptPlan 渲染（地图点位/items 跟随编辑实时刷新）
  const editedView = React.useMemo(() => {
    if (!editing || !draft) return null;
    const adapted = adaptPlan({ ...plan._raw, days: draft }, currentUsername);
    adapted.logs = plan.logs;
    return adapted;
  }, [editing, editVer]); // eslint-disable-line
```

并修改 `startModify`，编辑中先确认：

```jsx
  const startModify = () => {
    if (editing && !confirm("正在手动编辑，离开将丢弃未保存的修改。继续？")) return;
    if (!getAuth()) { onRequestLogin?.(); return; }
    if (!modQuery.trim() || !planId) return;
    onRequestModify?.(modQuery, planId);
  };
```

- [ ] **Step 2: 渲染切换**

把 TripDetailPage 中 `const day = plan.days[dayIdx];` 一段改为：

```jsx
  if (!plan) return null;
  const viewPlan = editing && editedView ? editedView : plan;
  const day = viewPlan.days[dayIdx];
```

（注意下方 JSX 中 `plan.days.map` 的 day-tabs、`plan.weather`、`plan.tips` 等保持读 `plan` 不变——天气/贴士不受编辑影响；只有 `day`（时间轴与地图）切到 viewPlan。）

day-header 区域改为（编辑态隐藏优化/回退按钮，显示入口按钮）：

```jsx
          <div className="day-header">
            <div className="day-theme">{day.theme}</div>
            {dayMsg && dayMsg.day === dayNo && <span className="day-opt-msg">{dayMsg.text}</span>}
            {!editing && planId && (
              <button className="optimize-btn" onClick={enterEdit}>✏️ 编辑行程</button>
            )}
            {!editing && hasAttractions && planId && (
              isOptimized ? (
                <button className="revert-btn" onClick={() => handleRevert(dayNo)}>↩ 回退</button>
              ) : (
                <button className="optimize-btn" disabled={optimizingDay === dayNo} onClick={() => handleOptimize(dayNo)}>
                  {optimizingDay === dayNo ? "优化中…" : "🔀 优化路线"}
                </button>
              )
            )}
          </div>
```

`<Timeline items={day.items} key={dayIdx} />` 处改为：

```jsx
          {editing ? (
            <>
              <EditToolbar canUndo={undoStack.length > 0} canRedo={redoStack.length > 0}
                saving={saving} saveErr={saveErr}
                onUndo={undo} onRedo={redo} onCancel={exitEdit} onSave={saveEdit} />
              <EditableTimeline rawTimeline={draft[dayIdx].timeline} ver={`${dayIdx}-${editVer}`}
                onReorder={handleReorder}
                onReplace={(idx) => setSearchTarget({ dayI: dayIdx, idx })}
                onDelete={handleDelete}
                onTimeChange={handleTimeChange}
                onAdd={(addType) => setSearchTarget({ dayI: dayIdx, idx: null, addType })} />
            </>
          ) : (
            <Timeline items={day.items} key={dayIdx} />
          )}
```

地图列 `<MapPanel day={day} dayIdx={dayIdx} />` 不用改（day 已来自 viewPlan）。

页面顶层（`concernModal` 渲染同级）追加搜索弹层渲染：

```jsx
      {searchTarget && (
        <PoiSearchModal
          city={plan.destination}
          kind={searchTarget.idx != null
            ? (draft[searchTarget.dayI].timeline[searchTarget.idx].type === "attraction" ? "attraction" : "restaurant")
            : (searchTarget.addType === "attraction" ? "attraction" : "restaurant")}
          title={searchTarget.idx != null ? "更换为…" : "添加…"}
          onPick={handlePoiPick}
          onClose={() => setSearchTarget(null)} />
      )}
```

底部「修改规划」query-card 在编辑态隐藏，整块包一层：

```jsx
      {!editing && (
        <div className="query-card" style={{ margin: "30px auto 0", maxWidth: 760 }}>
          {/* …原内容不变… */}
        </div>
      )}
```

- [ ] **Step 3: 手动冒烟**

刷新页面 → 生成或打开一份行程 → 点「✏️ 编辑行程」：工具栏出现、卡片可拖、撤销/重做生效、完成编辑后页面回到浏览态且数据已更新。控制台无报错。

- [ ] **Step 4: 提交**

```bash
git add frontend/pages.jsx
git commit -m "feat(frontend): 行程详情页接入手动编辑态（拖拽/换点/改时间/撤销重做/保存）"
```

---

### Task 7: 样式 — 编辑态 CSS

**Files:**
- Modify: `frontend/style.css`（文件末尾追加）

- [ ] **Step 1: 追加样式**

变量沿用现有主题（`--card / --line-2 / --accent / --second / --ink-3` 等已在 style.css 定义）：

```css
/* ── 行程手动编辑 ─────────────────────────────────── */
.edit-toolbar {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; margin-bottom: 14px;
  background: var(--card); border: 1px solid var(--line-2); border-radius: 12px;
  position: sticky; top: 10px; z-index: 20;
}
.edit-toolbar-hint { flex: 1; font-size: .78rem; color: var(--ink-3); }
.edit-save-err { flex: 1; font-size: .8rem; color: var(--accent); }
.edit-tool {
  font-size: .82rem; padding: 6px 14px; border-radius: 8px;
  border: 1px solid var(--line-2); background: var(--card); color: inherit; cursor: pointer;
}
.edit-tool:disabled { opacity: .4; cursor: default; }
.edit-tool.primary { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); font-weight: 700; }

.edit-list { display: flex; flex-direction: column; gap: 10px; }
.edit-card {
  display: flex; align-items: center; gap: 10px;
  background: var(--card); border: 1px solid var(--line-2); border-radius: 12px;
  padding: 12px 14px;
}
.edit-ghost { opacity: .45; border-style: dashed; border-color: var(--accent); }
.drag-grip { cursor: grab; color: var(--ink-4); font-size: 1.1rem; user-select: none; padding: 4px 2px; }
.drag-grip:active { cursor: grabbing; }
.edit-card-body { flex: 1; min-width: 0; }
.edit-card-title { display: flex; align-items: center; gap: 8px; font-weight: 700; }
.edit-dist { font-size: .72rem; color: var(--ink-3); font-weight: 400; }
.edit-card-meta { display: flex; align-items: center; gap: 12px; margin-top: 4px; font-size: .8rem; color: var(--ink-3); flex-wrap: wrap; }
.edit-card-acts { display: flex; gap: 6px; }
.edit-act {
  font-size: .75rem; padding: 4px 10px; border-radius: 99px;
  border: 1px solid var(--line-2); background: transparent; color: inherit; cursor: pointer;
}
.edit-act.danger:hover { border-color: var(--accent); color: var(--accent); }

.edit-empty { padding: 26px 0; text-align: center; color: var(--ink-3); font-size: .85rem; }
.edit-add-row { display: flex; gap: 8px; margin-top: 12px; }
.edit-add {
  font-size: .8rem; padding: 7px 16px; border-radius: 99px;
  border: 1px dashed var(--line-2); background: transparent; color: var(--ink-3); cursor: pointer;
}
.edit-add:hover { border-color: var(--accent); color: var(--accent); }

.time-edit { display: inline-flex; align-items: center; gap: 4px; }
.time-edit input[type="time"] {
  border: 1px solid var(--line-2); border-radius: 6px; padding: 2px 6px;
  background: var(--card); color: inherit; font: inherit; font-size: .78rem;
}
.time-edit.bad input { border-color: var(--accent); }
.time-edit-err { font-size: .72rem; color: var(--accent); }

.poi-search-card { width: min(520px, 92vw); }
.poi-search-bar { display: flex; gap: 8px; margin-top: 6px; }
.poi-search-bar .form-input { flex: 1; }
.poi-search-err { margin-top: 10px; font-size: .82rem; color: var(--accent); }
.poi-results { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; max-height: 320px; overflow-y: auto; }
.poi-result {
  text-align: left; padding: 10px 12px; border-radius: 10px;
  border: 1px solid var(--line-2); background: var(--card); color: inherit; cursor: pointer;
}
.poi-result:hover { border-color: var(--accent); }
.poi-result-name { display: block; font-weight: 700; }
.poi-result-meta { display: flex; gap: 10px; flex-wrap: wrap; font-size: .75rem; color: var(--ink-3); margin-top: 3px; }
```

注意：若 style.css 中无 `--ink-4` 变量，将 `.drag-grip` 的颜色换成 `var(--ink-3)`（先 `grep -n "ink-4" frontend/style.css` 确认）。

- [ ] **Step 2: 视觉检查**

刷新页面进入编辑态：工具栏吸顶、卡片间距正常、拖拽时 ghost 虚线高亮、弹层不超屏。

- [ ] **Step 3: 提交**

```bash
git add frontend/style.css
git commit -m "feat(frontend): 手动编辑态样式（工具栏/卡片/搜索弹层/时间输入）"
```

---

### Task 8: 端到端 QA 验收 + 文档收尾

**Files:**
- Modify: `CLAUDE.md`（前端架构文件清单加 edit.jsx）

- [ ] **Step 1: 运行后端测试全量回归**

Run: `python -m pytest tests/test_manual_edit_api.py tests/test_weather_mock.py -v`
Expected: 全部 PASS

- [ ] **Step 2: 浏览器 QA（用 /qa 或 preview 工具走查）**

验收清单（每项都要实际操作验证）：
1. 拖拽换序：拖动卡片 ⠿ → 顺序变化、时间段留在原位置、距离 pill 实时更新、右侧地图编号与路线跟随
2. 更换景点：点「↔ 更换」→ 搜索"总统府"→ 选中 → 卡片更新且保留原时间段
3. 更换餐厅：对午餐卡片操作，确认搜索弹层 placeholder 是餐厅文案、选中后 cost/address 更新
4. 改时间：点时间输入框改成 10:00–09:00 → 显示"开始须早于结束"且不提交；改成合法值 → 生效
5. 删除 + 新增：删掉一张卡 → 撤销恢复；底部「＋ 景点」添加成功（追加到末尾、时间为空）
6. 撤销/重做：连续做 3 步操作 → 撤销 3 次逐步回退 → 重做 2 次；新操作后重做按钮置灰
7. 保存：完成编辑 → 浏览态显示新顺序 → 刷新页面从历史打开 → 仍是编辑后版本
8. 守卫：有修改时点「取消」弹确认；浏览器刷新弹原生确认
9. 错误路径：断网（DevTools offline）点完成编辑 → 红条报错、编辑态不丢；恢复网络重试成功
10. 空态：删空一天所有条目 → 显示空态提示 → 保存成功

发现 bug 即修复并补提交，全部通过后继续。

- [ ] **Step 3: 更新 CLAUDE.md 前端文件清单**

`CLAUDE.md` 前端架构小节，在 `tweaks-panel.jsx` 行后加：

```
  edit.jsx          行程手动编辑（拖拽换序/搜索换点/时间编辑/撤销栈）
```

- [ ] **Step 4: 提交**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md 前端清单补充 edit.jsx"
```

---

## 自查记录

- **Spec 覆盖**：拖拽换序（T5/T6）✓ 换景点/饭店（T2/T5/T6）✓ 删除/新增（T5/T6）✓ 改时间（T5/T6）✓ 撤销/重做（T6）✓ 持久化+服务端重算距离（T3）✓ 守卫与错误处理（T6/T8）✓ 范围外项均未实现 ✓
- **类型一致性**：`searchPoi(city, kw, kind)` / `saveTimeline(plan_id, days)` 前后端字段对齐；`reorderKeepTimes` / `recalcDayDists` 命名在 T5 定义、T6 引用一致；`PoiSearchModal` props 与 T6 调用处一致
- **占位符**：无 TBD/TODO；所有代码步骤含完整代码
