<div align="center">

# 🌊 FloatTrip

### 让旅行规划像浮在平静水面上一样自然展开

FloatTrip 是一个旅游规划 Agent。它从网页攻略调研开始，抽取候选景点池，调用高德 POI 补齐真实坐标，按区域聚类分天，再生成带公交/步行路线段的地图可视化行程。

<p>
  <img alt="LangGraph" src="https://img.shields.io/badge/Agent-LangGraph-1C6BFF?style=flat-square">
  <img alt="LangChain" src="https://img.shields.io/badge/Orchestration-LangChain-0FA958?style=flat-square">
  <img alt="FastAPI" src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square">
  <img alt="Vite" src="https://img.shields.io/badge/Frontend-Vite-646CFF?style=flat-square">
  <img alt="Amap" src="https://img.shields.io/badge/Map-AMap-1677FF?style=flat-square">
  <img alt="Status" src="https://img.shields.io/badge/Status-MVP_Routing-7B61FF?style=flat-square">
</p>

<p>
  <strong>Homepage Preview</strong>
</p>

<img alt="FloatTrip 首页规划入口" src="localstatic/image/indeximage1.png">

</div>

## 📝 Changelog

每次向 GitHub push 新版本前，都需要在这里追加版本记录。每条记录必须包含版本编号、push 日期和本版本更新内容，便于后续追溯。

版本编号建议遵循 `v主版本.次版本.修订版本`：

- 主版本：产品方向或核心架构发生明显变化
- 次版本：新增功能、接口、页面或重要链路
- 修订版本：修复问题、补充文档、调整样式或小范围优化

### v0.1.0 - 2026-05-23

本版本为 FloatTrip MVP 路线规划链路版本，完成从网页调研到前端展示的基础闭环。

- 新增独立 `frontend/` Vite 前端工程，默认请求 `POST /api/planner/generate`，展示调研摘要、按天路线、时长、距离和路径状态
- 后端补齐完整规划接口 `POST /api/planner/generate`：网页调研、候选景点抽取、高德 POI 补坐标、分天聚类、真实路线规划一次完成
- 新增 `POST /api/planner/transit-routes`，支持对已带 POI 坐标的候选景点生成高德公交/步行路线段与 polyline path
- 保留 `POST /api/planner/cluster-routes` 作为仅分天聚类的路线预览接口
- 将网页调研、候选池抽取和 POI 富化沉淀到 `backend/app/services/`
- 将真实通行时间矩阵、每日 2~4 景点选择、暴力枚举访问顺序和步行兜底沉淀到 `backend/app/planning/transit_routes.py`
- 将旧版实验脚本与静态原型迁移到 `localexperiments/`、`localstatic/`，根目录 README 路径同步更新

### v0.1.1 - 2026-05-23

本版本为后端瘦身版本，只保留“用户输入提交 -> 后端完整规划 -> 前端展示结果”的主链路。

- 删除后端 `POST /api/planner/cluster-routes` 和 `POST /api/planner/transit-routes` 两个非前端主流程接口
- 删除占位性质的 `backend/app/agents/`、`backend/app/tools/`、未实现路线矩阵/优化器和旧行程文案 schema
- 收窄请求/响应 schema，只保留 `/api/planner/generate` 与前端渲染需要的数据契约
- 精简后端 API 测试，保留健康检查、完整规划链路、用户景点文本拆分和必去景点合并测试
- 同步 README 的 API、架构和目录说明，避免文档继续暴露已移除接口

### v0.2.0 - 2026-05-23

本版本将候选景点池升级为 Tavily markdown 调研 + DeepSeek 结构化抽取链路。

- 搜索源正式切换为 Tavily，抓取结果页后清噪提纯为 markdown 攻略内容
- 候选景点抽取改为 LangGraph 编排 DeepSeek 结构化输出，返回景点名称和偏好符合分
- DeepSeek 抽取后由代码在 markdown 原文中统计景点提及频率，并按提及频率、偏好符合分降序排序
- 移除后端主链路中的静态后缀正则候选景点抽取，不再使用 SearchAPI Baidu / DuckDuckGo 兜底
- `research_summary` 增加候选池构建器、markdown 文档数和 DeepSeek 模型信息，便于排查候选池质量
- 补充 markdown 清噪、候选池排序和 DeepSeek 失败返回 503 的测试

### v0.3.0 - 2026-05-25

本版本将候选景点池生成升级为热门候选景点池 Agent，让搜索覆盖从固定天数攻略扩展到热门景点和必去榜单。

- 新增 `generate_hot_candidate_pool()` 候选景点池 Agent，串联多 query 规划、Tavily 调研、markdown 清噪、DeepSeek 抽取和候选排序
- DeepSeek 先生成搜索计划，再由代码强制补入“热门旅游景点 / 必去景点 / 景点推荐”等宽泛搜索词，避免候选池只受游玩天数限制
- 保留网页提及频率和偏好符合分作为热门候选池排序信号，再继续传给高德 POI enrich 和后续路线规划链路
- `research_summary.query_plan` 返回最终使用的多 query 搜索计划，便于排查候选池来源
- 补充 query 兜底、搜索计划节点和 planner API 新入口测试

## ✨ Features

- 从 Tavily 搜索结果抓取攻略网页，优先覆盖本地宝和携程攻略，并提纯为去除页面噪声的 markdown 信息源
- 用 DeepSeek 从 markdown 中结构化抽取候选景点和偏好符合分
- 按 markdown 原文中的景点提及次数和偏好符合分生成候选景点排序信号
- 使用高德 POI 校验真实地点并补齐坐标
- 按地理区域聚类分天，每天选择 2~4 个相对紧凑的景点
- 调用高德公交路线规划生成通行时间矩阵和路线 path，近距离失败时回退步行路线
- 用暴力枚举寻找当天最短访问顺序，接口返回 `route_segments`、`duration_matrix_seconds`、`optimized_order` 和每日汇总指标
- 前端可直接展示完整规划结果；没有高德 JS Key 时也会展示后端 JSON、路线顺序、时长和距离

FloatTrip 的产品体验围绕“平静水面上的自然浮动”展开：现代柔和前端、淡蓝渐变光感、悬浮水面感、弱分割线和强交互动效，共同承载轻松的一键旅行规划体验。

## 🖼 Preview

| 旅行规划入口 | 首页价值展示 |
| --- | --- |
| ![FloatTrip 首页规划入口](localstatic/image/indeximage1.png) | ![FloatTrip 首页使用场景](localstatic/image/image%20copy.png) |

![FloatTrip 首页登录与旅行库入口](localstatic/image/image.png)

当前仓库保留了早期静态原型，可直接打开查看：

- `localstatic/docs/preview.html`
- `localstatic/docs/indexv1.html`
- `localstatic/docs/plannerv1.html`
- `localstatic/docs/plannerv2.html`
- `localstatic/docs/route-map.html`

## 🧭 How It Works

第一版规划 Agent 先把“值得去哪里”做稳，再逐步解决“当天怎么走”：

```text
DeepSeek 热门候选景点池 Agent
  -> 生成多 query 搜索计划，覆盖热门景点、必去榜单、景点推荐、经典路线和偏好玩法
  -> Tavily 多 query 搜索，优先抓取本地宝 / 携程攻略等攻略页，并清噪提纯为 markdown
  -> DeepSeek 结构化抽取热门候选景点和偏好符合分
  -> 代码统计 markdown 中的景点提及频率并排序
  -> 用户必去 / 避开景点合并过滤
  -> 高德 POI 过滤与坐标补齐
  -> 按地理区域聚类分天
  -> 每天选择 2~4 个景点
  -> 调用高德构建公交/步行通行时间矩阵
  -> 暴力枚举优化当天访问顺序
  -> 返回前端可画线的按天路线 JSON
```

当前后端主链路在 `backend/app/workflows/research_route_planner.py`：

1. `generate_hot_candidate_pool()` 运行热门候选景点池 Agent：先由 DeepSeek 生成多 query 搜索计划，并强制补入“热门旅游景点 / 必去景点 / 景点推荐”等宽泛搜索词。
2. Agent 调用 Tavily 多 query 搜索攻略网页，把网页正文清噪提纯为 markdown，再由 DeepSeek 结构化抽取热门候选景点和偏好符合分。
3. 代码统计景点名在 markdown 中的提及频率，按提及频率和偏好分排序输出候选景点池。
4. `enrich_candidates_with_amap()` 调用高德 POI，把候选景点落到真实地点和坐标。
5. `build_daily_transit_route_plan()` 按天聚类、选择每日景点、查询高德路线、优化访问顺序。
6. `TripRoutePlanResponse` 返回可供前端地图和列表消费的结构化结果。

`localexperiments/` 中保留了候选池、搜索源、高德 POI、聚类地图和路线 JSON 的实验脚本，方便继续做算法验证。

## 🚀 Quick Start

先按 `.env.example` 在项目根目录准备 `.env.local`：

```bash
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash
AMAP_API_KEY=
TAVILY_API_KEY=
BAIDU_APPBUILDER_API_KEY=
```

安装并启动后端：

```bash
python3 -m pip install -r requirements-backend.txt
python3 -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8020 --reload
```

启动前端：

```bash
cd frontend
npm install
npm run dev
```

页面地址：

```text
http://127.0.0.1:8088
```

如需地图渲染，把 `frontend/amap-config.example.js` 复制为 `frontend/amap-config.local.js` 并填入高德 JS Key。没有 JS Key 时，前端仍会真实请求后端并展示规划 JSON、调研摘要和路线指标。

## 🔌 API

当前后端提供：

- `GET /health`：健康检查
- `POST /api/planner/generate`：从网页调研开始生成完整路线，适合前端主流程

`/api/planner/generate` 最小请求示例：

```json
{
  "destination": "南京",
  "days": 3,
  "preferences": ["历史文化", "博物馆"],
  "preferred_spots": ["中山陵、明孝陵"],
  "avoided_spots": ["玄武湖"],
  "max_search_results": 8,
  "max_candidates": 28
}
```

核心响应字段：

- `schema_version`：完整路线当前为 `floattrip_daily_transit_routes.v1`
- `route_mode`：固定为 `amap_transit`
- `research_summary`：搜索词、搜索结果数、有效网页数、候选池数量和来源列表
- `days[].spots`：当天景点点位
- `days[].route_order`：优化后的访问顺序名称
- `days[].route_segments`：两个景点之间的路线段、时长、距离、费用摘要和 `path`
- `days[].summary_metrics`：每日景点数量、总时长、失败路段数量和路线状态

## 🧪 Tests

运行后端测试：

```bash
python3 -m unittest discover backend/tests
```

运行前端构建检查：

```bash
cd frontend
npm run build
```

## 🧱 Architecture

| Layer | Stack / Responsibility |
| --- | --- |
| Agent 编排 | LangGraph / LangChain |
| Agent 测试与迭代 | LangSmith |
| 后端 | FastAPI |
| 前端 | Vite 单页应用 |
| 地图与 POI | 高德地图 Web 服务与高德 JS API |
| 信息源 | Tavily 搜索、清噪 markdown 攻略、DeepSeek 结构化候选池 |
| 规划中间层 | 候选池、POI 坐标补全、地理聚类、通行时间矩阵、访问顺序优化 |

站点入口约定：

- 官网前台：`www.floattrip.com`
- 用户工作台：`app.floattrip.com`
- 后台管理台：`admin.floattrip.com`

当前后端分层：

```text
api        -> 面向前端的主链路接口入口
workflows  -> 串联完整规划流程
services   -> 网页调研、候选池抽取、POI 富化等业务服务
planning   -> 分天聚类、真实路线规划和访问顺序优化
providers  -> 高德 POI、公交路线和步行路线适配
schemas    -> /api/planner/generate 与前端展示共享的数据契约
```

## 📁 Project Structure

- `backend/app/main.py`：FastAPI 应用入口，注册 CORS、健康检查和规划接口
- `backend/app/api/`：后端接口路由，目前只保留完整规划主接口
- `backend/app/schemas/`：前端请求、地图点位和路线计划的数据结构
- `backend/app/workflows/`：规划流程编排入口，串联完整生成链路
- `backend/app/services/`：网页调研、候选池抽取和高德 POI 富化
- `backend/app/planning/`：确定性规划模块，包含分天聚类、真实路线和访问顺序优化
- `backend/app/providers/`：外部服务能力封装，目前包含高德 POI、公交路线和步行路线能力
- `backend/tests/`：后端主接口、聚类、高德 provider 和规划链路测试
- `frontend/`：Vite 前端工程，默认对接 `http://127.0.0.1:8020`
- `localexperiments/`：旅行搜索、候选池抽取、POI 过滤、聚类、路线 JSON 和调试地图实验脚本
- `localstatic/docs/`：产品 PRD 与早期静态原型页面
- `localstatic/image/`：官网首页示例图片
- `assets/`：README 和原型使用的早期静态素材

## 🗺 Roadmap

- 将当前启发式网页调研收敛为正式 LangGraph Agent 节点
- 接入 LLM 生成自然语言日程说明、餐饮建议和注意事项
- 增强路线优化：支持 2-opt、开闭馆时间、酒店起终点和用户节奏
- 将高德地图前端展示和路线段交互打磨为正式用户工作台体验
- 增加 LangSmith 评测集，覆盖候选池质量、POI 命中率和路线可执行性
