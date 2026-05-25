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
- Agent 配备真实搜索 + markdown 清噪工具，候选池证据不足时会继续生成补充 query 并迭代搜索
- 保留网页提及频率和偏好符合分作为热门候选池排序信号，再继续传给高德 POI enrich 和后续路线规划链路
- `research_summary.query_plan` 返回最终使用的多 query 搜索计划，便于排查候选池来源
- 补充 query 兜底、搜索计划节点和 planner API 新入口测试

### v0.4.0 - 2026-05-25

本版本将 FloatTrip 从“路线规划结果”升级为“可阅读、可补全、可展示的行程详情 Agent 链路”。

- 新增 `POST /api/planner/itinerary-details`，基于已有路线计划补齐每日主题、天气、时间线、午晚餐、注意事项和图片字段
- 搜索 Agent 明确升级为两阶段搜索：先规划热门/必去/偏好玩法 query，再根据候选数量和网页证据不足情况生成 follow-up query 继续补搜
- `search_markdown_research_tool()` 作为搜索 Agent 的真实工具，统一执行 Tavily 多 query 搜索、网页抓取、markdown 清噪、多轮结果合并和 URL 去重
- 新增行程详情 Agent：用 DeepSeek 生成每日主题、高峰提醒和 Unsplash 图片搜索 query，并提供规则兜底
- 接入高德 MCP provider，优先通过 MCP 获取城市天气和周边餐饮 POI，失败时回退高德 Web API 或本地兜底建议
- 新增 Unsplash 图片服务，为景点卡和每日摘要卡补图；不同景点图片做 URL/id 去重，摘要卡按当天主题搜图，失败时回退当天景点图
- 优化行程详情时间线：单大型景点拆成上午/下午游览，两景点按上午/下午分布，确保午餐和晚餐之间仍有景点活动
- 新增 `frontend/itinerary-detail.html` 用户工作台详情页，展示水面玻璃感摘要卡、每日时间线、餐饮推荐、路线摘要、注意事项和图片背景
- 摘要卡支持天气图标与主题背景图，时间线节点支持交通和餐饮图标，景点图片不再显示摄影署名文字
- 新增规划日志服务 `planner_logging`，把 LLM 候选池、高德富化候选池、聚类输入和聚类输出写入 `backend/logs/` 便于追溯
- 优化聚类输入截取：必去景点优先进入聚类窗口，并补充聚类、MCP、图片搜索、行程详情和日志测试
- `.env.example` 增加 `AMAP_MCP_URL` 和 `UNSPLASH_ACCESS_KEY`，支持详情 Agent 的天气/餐饮/图片能力配置

## ✨ Features

- 从 Tavily 搜索结果抓取攻略网页，优先覆盖本地宝和携程攻略，并提纯为去除页面噪声的 markdown 信息源
- 用 DeepSeek 从 markdown 中结构化抽取候选景点和偏好符合分
- 按 markdown 原文中的景点提及次数和偏好符合分生成候选景点排序信号
- 使用高德 POI 校验真实地点并补齐坐标
- 按地理区域聚类分天，每天选择 2~4 个相对紧凑的景点
- 调用高德公交路线规划生成通行时间矩阵和路线 path，近距离失败时回退步行路线
- 用暴力枚举寻找当天最短访问顺序，接口返回 `route_segments`、`duration_matrix_seconds`、`optimized_order` 和每日汇总指标
- 行程详情 Agent 可补齐每日主题、天气、午晚餐、时间线、注意事项和景点/主题图片
- 前端可展示完整规划结果和详情页；没有高德 JS Key 时也会展示后端 JSON、路线顺序、时长和距离

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
  -> 搜索 Agent 生成多 query 搜索计划，覆盖热门景点、必去榜单、景点推荐、经典路线和偏好玩法
  -> 搜索 Agent 调用 search_markdown_research_tool，执行 Tavily 搜索、网页抓取、markdown 清噪和 URL 去重
  -> DeepSeek 结构化抽取热门候选景点和偏好符合分
  -> 如果文档证据或候选数量不足，搜索 Agent 继续生成补充 query 并再次调用搜索工具
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

1. `generate_hot_candidate_pool()` 运行热门候选景点池 Agent：先由搜索 Agent 生成多 query 搜索计划，并强制补入“热门旅游景点 / 必去景点 / 景点推荐”等宽泛搜索词。
2. 搜索 Agent 调用 `search_markdown_research_tool()` 执行 Tavily 真实搜索、网页抓取和 markdown 清噪，并把多轮结果合并去重。
3. DeepSeek 从累计 markdown 中结构化抽取热门候选景点和偏好符合分，代码统计景点名在 markdown 中的提及频率并排序。
4. 如果候选数量或文档证据不足，搜索 Agent 会基于已搜索 query 和当前候选池继续生成补充 query，再次调用搜索工具。
5. `enrich_candidates_with_amap()` 调用高德 POI，把候选景点落到真实地点和坐标。
6. `build_daily_transit_route_plan()` 按天聚类、选择每日景点、查询高德路线、优化访问顺序。
7. `TripRoutePlanResponse` 返回可供前端地图和列表消费的结构化结果。

`localexperiments/` 中保留了候选池、搜索源、高德 POI、聚类地图和路线 JSON 的实验脚本，方便继续做算法验证。

## 🚀 Quick Start

先按 `.env.example` 在项目根目录准备 `.env.local`：

```bash
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash
AMAP_API_KEY=
AMAP_MCP_URL=https://mcp.amap.com/mcp?key=你的高德Key
TAVILY_API_KEY=
BAIDU_APPBUILDER_API_KEY=
UNSPLASH_ACCESS_KEY=
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
- `POST /api/planner/itinerary-details`：基于已有路线计划补齐行程详情页的每日主题、天气、餐饮、图片和时间线

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
- `days[].itinerary_detail`：详情接口补齐后的每日主题、封面图、天气、活动时间线、餐饮推荐和注意事项

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
