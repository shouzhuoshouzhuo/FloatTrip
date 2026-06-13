# 行程手动编辑（拖拽换序 / 更换景点 / 改时间）设计文档

日期：2026-06-12
状态：已与用户确认

## 背景与目标

Agent 生成的行程详情目前只能整体走 LLM「修改规划」流程调整。本功能让用户在行程详情页直接二次编辑：

- 拖拽丝滑调整一天内景点/餐厅的游玩顺序
- 更换景点 / 更换饭店（手动输入关键词搜索高德）
- 删除、新增条目
- 编辑每个条目的游玩时间段
- 逐步撤销 / 重做
- 修改持久化保存（历史页打开是编辑后版本）

## 已确认的需求决策

| 决策点 | 结论 |
|---|---|
| 持久化 | 需要，原地更新 plan_json，不产生新 plan_id |
| 撤销 | 逐步撤销（操作栈），仅当前会话有效，刷新后栈清空但已保存修改还在 |
| 换景点来源 | 用户手动输入关键词，经后端代理搜高德（不复用候选池） |
| 互换范围 | 仅同一天内调整顺序，不支持跨天移动 |
| 时间/距离处理 | 纯前端机械处理：换序后时间段留在位置上不跟卡走；距离用 haversine 重算；时间可手动编辑 |
| 交互形态 | 显式编辑模式：点「编辑行程」进入编辑态，浏览态保持干净 |
| 拖拽实现 | SortableJS（CDN 引入），适配无构建步骤的 React 架构 |

## 整体架构

```
编辑态（前端内存 + 撤销栈）
  拖拽换序 ──┐
  更换/删除/新增 ──┤ 每步操作 → 改 draft → 重算当天距离 → 压栈 → 重渲染
  修改时间 ──┘
                ↓ 点「完成编辑」
PUT /api/plan/{plan_id}/timeline  →  合并进 plan_json → update_plan_json（现有，含所有权校验）
                ↓
「更换/新增」搜索弹层  →  GET /api/poi/search  →  高德文本搜索（现有 client + Redis 缓存）
```

编辑过程后端零参与，只负责搜索代理和最终保存。

## 后端（plan_routes.py 新增 2 个接口）

### 1. `GET /api/poi/search?city=南京&kw=颐和路&kind=attraction|restaurant`

- 需登录（Bearer token），防止高德配额被白嫖
- `kind=attraction`：复用 `search_attraction_pois`（types=风景名胜）
- `kind=restaurant`：同一文本搜索 API，types=餐饮服务
- 结果经现有 `poi_to_spot` 解析为统一结构（名称/评分/地址/坐标/开放时间/照片），返回前 8 条
- 失败返回 4xx/5xx + detail，前端弹层内展示

### 2. `PUT /api/plan/{plan_id}/timeline`

- Body：`{ days: [{day: 1, timeline: [...]}, ...] }`
- 只接收 timeline，服务端合并进已存 plan_json；不允许前端整体覆盖 plan（保护 weather/preferences 等字段）
- 校验：plan 存在且属于当前用户；day 序号在范围内；timeline 每项含 name/type
- `dist_from_prev_km` 服务端用 `haversine_km` 重算后落库，不信任前端值（前端算的仅用于即时显示）
- 持久化走现有 `update_plan_json`

### 架构决策：保存不产生新 plan_id

LLM「修改规划」生成新记录（parent_id 链）；手动编辑是高频小操作，每次保存生成新记录会刷爆历史页，故原地更新。代价：AI 原版被覆盖。「恢复 AI 原版」快照按 YAGNI 暂不做，plan_json 整体替换的写法未来加快照字段不冲突。

## 前端（TripDetailPage）

### 状态模型

```
editing: bool                  是否处于编辑态
draft:   _raw.days 的深拷贝    编辑只改 draft，不碰展示中的 plan
undoStack / redoStack: []      元素 = 整份 draft.days 快照（深拷贝）
```

- 快照栈而非操作/逆操作栈：一天 timeline 不到 10 个对象，深拷贝成本可忽略，代码简单一个量级
- 任何新操作清空 redoStack（标准语义）
- 进入编辑：`draft = structuredClone(plan._raw.days)`，栈清空
- 完成编辑：PUT 保存 → 成功后用返回 plan 重新 `adaptPlan` 刷新、退出编辑态
- 取消编辑：丢弃 draft，无请求

### 五种编辑操作（每种 = 改 draft → 重算当天 dist → 压栈）

1. **拖拽换序**：SortableJS 实例仅编辑态挂载（`handle: '.drag-grip'`），`onEnd` 按 oldIndex/newIndex 移动数组。React 集成：onEnd 同步 state + 容器 `key={编辑版本号}` 强制重挂载，杜绝 DOM/state 漂移。时间段留在位置上不跟卡走（第 1 位永远用原第 1 位的时间段）。
2. **更换景点/饭店**：卡片「↔ 更换」→ 搜索弹层（城市自动取 plan.destination）→ 调 `/api/poi/search` → 选中后替换条目：继承原条目的时间段与 period（饭店继承 lunch/dinner 类型），其余字段来自新 POI。
3. **删除**：卡片「✕」直接移除，撤销栈兜底，不弹确认。
4. **新增**：每天 timeline 底部「+ 添加景点/餐厅」，同一搜索弹层，追加到当天末尾，时间段默认空。
5. **改时间**：编辑态点时间文本 → 两个 `<input type="time">`（开始/结束），失焦或回车提交。仅校验开始 < 结束；不校验与相邻卡片重叠（机械处理定位）。

### 距离与地图

每步操作后前端 haversine（照抄 helpers.py 公式）重算当天相邻条目 `dist_from_prev_km`，仅供显示。`mapPoints` 跟随 draft 重新生成；现有 `MapPanel` 已支持点位签名变化重画，无需改动。

### 工具栏与守卫

- 编辑态顶部工具栏：`↩ 撤销`（栈空置灰）｜`↪ 重做`｜`✕ 取消`｜`✓ 完成编辑`
- 编辑态允许切换 Day tab（draft 含全部天，撤销栈全局一条）
- 有未保存修改时点「取消」「修改规划」或离开页面 → confirm 提示丢弃

### 错误处理

- 搜索失败/无结果：弹层内提示「没找到，换个关键词试试」，不打断编辑态
- 保存失败（网络/401/404）：保留编辑态与 draft，顶部红条提示重试，编辑成果不丢
- 一天被删空：允许保存，卡片区显示空态提示

## 依赖

- SortableJS：`index.html` 加 CDN `<script>`（与现有 React/Babel CDN 引入方式一致）

## 测试

- **后端**（pytest）：
  - `/api/poi/search`：kind 两分支、未登录 401
  - `PUT timeline`：所有权校验（他人 plan 404/403）、day 越界 422、距离服务端重算正确
- **前端**（无测试框架，项目惯例走 `/qa` 浏览器验收）：
  - 拖拽换序、换景点、改时间、删除、新增
  - 撤销/重做逐步回退
  - 保存后刷新仍生效；历史页打开为编辑后版本
  - 保存失败时编辑态不丢

## 范围外（明确不做）

- 跨天移动条目
- LLM 参与时间重排或开放时间校验
- 「恢复 AI 原版」快照
- 跨会话撤销
