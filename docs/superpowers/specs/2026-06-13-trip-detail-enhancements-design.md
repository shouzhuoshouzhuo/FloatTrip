# 行程详情页增强功能设计文档

**日期**：2026-06-13  
**分支**：feature/manual-edit  
**范围**：前端行程详情页 + 后端数据层

---

## 一、需求概览

| 功能 | 层级 |
|------|------|
| 地图路线只连景点，不连餐厅 | 前端 |
| 卡片间导航行（任意相邻两项） | 前端 + 地图 |
| 周边搜索（风景名胜/餐饮服务） | 前端 + 后端新接口 |
| 景点/餐厅卡片展示更多高德字段 | 前端 + 后端数据层 |
| 候选景点推荐横滚条（可拖拽替换） | 前端 + 后端 finalize |
| 优化路线确认弹窗 | 前端 |
| 优化后餐厅按新顺序重新插入 | 后端 |
| 主题内联编辑 | 前端（编辑态） |
| Hotel / Notes 字段 | 前端 + 后端新接口 |

---

## 二、架构决策

**Hotel / Notes / 主题编辑 落库方案：扩展 final_plan JSON blob（方案 A）**

理由：final_plan 已作为 JSON blob 存入 SQLite，hotel/notes/day_themes 是 plan 的附属元数据，生命周期一致。复用现有 `update_plan_json`，不需要 ALTER TABLE 或新建表。

---

## 三、后端变更

### 3.1 `app/providers/amap/poi.py` — `poi_to_spot` 补全字段

新增 `address`（归一化地址字符串）和 `tel`（电话，无则 null）：

```python
"address": normalize_address(poi.get("address", "")),
"tel": str(poi.get("tel") or "").strip() or None,
```

同步在 `restaurant_to_dict`（`helpers.py`）中补充 `open_time`、`tel`、`category`（高德 `type` 字段的第三段，如「湘菜」）。

### 3.2 `app/planning/nodes.py` — `finalize_node` 附上候选景点池

在 final_plan 里增加 `candidate_spots` 字段：已排入行程的景点排除，剩余 pois 最多取前 20 个，字段：`name / rating / photo / location / open_time / address`。

```python
placed_names = {s["name"] for day in state.route for s in day.get("spots", [])}
candidate_spots = [
    {k: v for k, v in s.items() if k in ("name","rating","photo","location","open_time","address")}
    for s in state.pois if s["name"] not in placed_names
][:20]
final_plan["candidate_spots"] = candidate_spots
```

### 3.3 `app/api/plan_routes.py` — 两个新端点

**`GET /api/poi/nearby`**

封装 `search_around_pois`，按 `distance` 字段排序后返回：

```
Query params: lat, lng, type（风景名胜 | 餐饮服务）, radius=1500
Response: { results: [{name, rating, address, distance, location, photo, tel, open_time}] }
```

**`PUT /api/plan/{plan_id}/metadata`**

Body: `{ hotel, notes, day_themes: {"1": "新主题"} }`

用 `update_plan_json` merge 进 final_plan JSON，不影响 timeline 字段。需要 JWT 鉴权，只允许 plan 所有者操作。

### 3.4 `optimize_day` 餐厅重新插入

优化完 TSP 排序后，用与 `finalize_node` 相同的规则重新插入餐厅：
- 午餐：插在上午最后一个景点之后
- 晚餐：插在下午最后一个景点之后

优先级：若优化后没有上午/下午景点，餐厅插在第一/最后景点后。

---

## 四、前端变更

### 4.1 `api.js`

| 改动 | 说明 |
|------|------|
| `initAmapForDay` | `path` 只取 `kind !== "meal"` 的点，餐厅标记保留但不连线 |
| 新增 `searchNearby(lat, lng, type, radius)` | 调 `/api/poi/nearby` |
| 新增 `saveMetadata(planId, data)` | 调 `PUT /api/plan/{id}/metadata` |
| `adaptPlan` | 补传 `address`、`tel`、`candidate_spots`、`hotel`、`notes`；各天 theme 可被 `day_themes` 覆盖 |

### 4.2 `components.jsx`

**`AttractionCard` 新增字段展示**：`address`（📍）、`tel`（📞，有才显示）、`cost`（💰 门票，有才显示）。

**`MealCard` 新增字段展示**：`open_time`（🕐）、`tel`（📞，有才显示）、`category`（菜系）。

**新增 `NavRow` 组件**

时间轴每两个相邻 item 之间插入一个 `NavRow`（两者均有坐标才渲染）：
- 显示直线距离（来自已有 `dist_from_prev_km`）
- 一个「🧭 导航」按钮
- 点击 → 向父组件发出 `{from: itemA.location, to: itemB.location}`，`MapPanel` 接收后触发 `Driving.search(A, B)`，覆盖全日路线
- 再次点击同一行 → 取消，恢复全日景点路线

**新增 `RecommendStrip` 组件**

位置：day-tabs 下方、时间轴上方，高度约 120px，横向滚动。
- 数据来源：`plan.candidate_spots`
- 每卡展示：缩略图 / 名称 / ★评分 / 开放时间
- 非编辑态：只读（不可拖拽）
- 编辑态：`draggable="true"`，时间轴景点卡片设为 drop target；drop 时调 `applyEdit` 替换目标景点字段，时间段保留

**新增 `NearbySearchModal` 组件**

景点卡片内「📍 周边搜索」按钮打开：
- 两个 Tab：附近景点 / 附近餐厅
- 默认 radius=1500m，可选 500 / 1000 / 1500 / 3000
- 结果按距离排列，展示 name / ★rating / distance / address

### 4.3 `pages.jsx`

**`TripDetailPage` 变更**：
- 优化路线前弹 `confirm`：「将按最短路程优化景点游玩顺序，餐厅需要你重新规划」
- 底部新增 Hotel（单行）+ Notes（多行）输入区，始终可编辑（不依赖编辑态）
- 有改动时显示「保存行程备注」按钮 → 调 `saveMetadata`
- `MapPanel` 接收 `activeNavPair` prop，用于响应 `NavRow` 的导航事件

### 4.4 `edit.jsx`

- 主题内联编辑：编辑态下 `day-header` 的主题旁加 ✏️，点击切换 `<input>`，走 `applyEdit` 修改 `draft[dayIdx].theme`，进撤销栈
- `RecommendStrip` 拖拽 drop 处理已在 `applyEdit` 里，`edit.jsx` 导出 `handleSpotDrop(dayI, targetIdx, candidateSpot)`

---

## 五、数据流

```
LLM Pipeline
  └─ finalize_node
       ├─ final_plan.days[].timeline  (景点 + 餐厅，含 address/tel)
       └─ final_plan.candidate_spots  (未排入行程的候选景点池，≤20条)

PUT /api/plan/{id}/metadata
  └─ update_plan_json(plan_id, {hotel, notes, day_themes})
       └─ SQLite trips.plan_json (merge，不覆盖 timeline)

GET /api/poi/nearby
  └─ search_around_pois(location, type, radius)
       └─ 按 distance 排序返回
```

---

## 六、不在本次范围内

- 餐厅导航后的地图 marker 高亮（周边搜索结果点击 → 地图跳转）
- 酒店预订外链集成
- 多设备同步（hotel/notes 只在当前 plan JSON 里，不跨设备同步到其他 plan）
