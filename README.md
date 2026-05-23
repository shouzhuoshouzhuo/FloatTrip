<div align="center">

# 🌊 FloatTrip

### 让旅行规划像浮在平静水面上一样自然展开

FloatTrip 是一个旅游规划 Agent。它从旅行信息源中汇总候选景点，过滤真实 POI，按区域组织每日候选点，并逐步生成可执行路线与自然语言行程。

<p>
  <img alt="LangGraph" src="https://img.shields.io/badge/Agent-LangGraph-1C6BFF?style=flat-square">
  <img alt="LangChain" src="https://img.shields.io/badge/Orchestration-LangChain-0FA958?style=flat-square">
  <img alt="FastAPI" src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square">
  <img alt="Amap" src="https://img.shields.io/badge/Map-AMap-1677FF?style=flat-square">
  <img alt="Status" src="https://img.shields.io/badge/Status-Planning_MVP-7B61FF?style=flat-square">
</p>

<p>
  <strong>Homepage Preview</strong>
</p>

<img alt="FloatTrip 首页规划入口" src="static/image/indeximage1.png">

</div>

## 📝 Changelog

每次向 GitHub 推送版本时，在这里记录本次新增能力和关键调整。

### 2026-05-23

- 新增 FastAPI 后端骨架，提供健康检查与按天聚类路线预览接口
- 将地理聚类核心迁入 `backend/app/planning/`，旧 `tools/geo_day_cluster.py` 保留兼容入口
- 抽出高德 POI 公共能力到 `backend/app/providers/`，为后续路线矩阵、沿途饭店和地图展示打底
- 增加后端 schema、workflow、tool/agent 边界和测试，补充 `requirements-backend.txt`
- 补齐旅行攻略抓取、markdown 候选景点抽取、高德 POI 过滤与坐标补全链路
- 增加按地理距离聚类分天与聚类调试地图，为后续按通行时间规划日路线打底
- 增加搜索源、候选池、POI 和地图渲染相关工具说明与测试
- 重排 README 首页结构，增加项目 badges、三张首页示例图和版本 Changelog

## ✨ Features

- 从攻略网页和 markdown 信息源抽取候选景点，而不是只返回一段聊天答案
- 按攻略中景点出现次数构建第一版候选景点排序信号
- 使用高德 POI 过滤候选景点并补齐坐标，让候选池落到真实地点
- 按地理距离聚类分天，为后续每日路线优化准备结构化输入
- 渲染聚类调试地图，便于开发阶段核对候选点和分天结果
- 预留搜索、定位、通行时间矩阵和自然语言行程生成链路

FloatTrip 的产品体验围绕“平静水面上的自然浮动”展开：现代柔和前端、淡蓝渐变光感、悬浮水面感、弱分割线和强交互动效，共同承载轻松的一键旅行规划体验。

## 🖼 Preview

| 旅行规划入口 | 首页价值展示 |
| --- | --- |
| ![FloatTrip 首页规划入口](static/image/indeximage1.png) | ![FloatTrip 首页使用场景](static/image/image%20copy.png) |

![FloatTrip 首页登录与旅行库入口](static/image/image.png)

当前仓库保留了早期静态原型，可直接打开查看：

- `static/docs/preview.html`
- `static/docs/indexv1.html`
- `static/docs/plannerv1.html`

## 🧭 How It Works

第一版规划 Agent 先把“值得去哪里”做稳，再继续解决“当天怎么走”：

```text
网页搜索 / 攻略内容抓取
  -> 候选景点抽取与出现次数打分
  -> 高德 POI 过滤与坐标补齐
  -> 按地理区域聚类分天
  -> 每天选择 2~4 个景点
  -> 调用高德构建通行时间矩阵
  -> 暴力枚举 / 2-opt 优化当天访问顺序
  -> LLM 生成自然语言行程
```

当前仓库已经实现候选景点进入按天区域聚类前后的开发链路：

1. 抓取网页正文并转成 markdown 信息源：`tools/fetch_webpage_content.py`
2. 从 markdown 攻略抽取候选景点池：`tools/langgraph_markdown_candidate_pool.py`
3. 输出候选池 JSON，例如 `/tmp/markdown_candidates.json`
4. 用高德 POI 过滤候选景点并补齐坐标：`tools/amap_poi_filter.py`
5. 输出带 POI 坐标的候选池 JSON，例如 `/tmp/amap_candidates.json`
6. 按地理距离聚类候选点：`tools/geo_day_cluster.py`
7. 渲染聚类调试地图：`tools/render_geo_day_clusters_map.py`

`tools/` 中还保留了百度、Tavily、SearchAPI 等不同搜索入口，以及高德公交通行时间脚本 `tools/amap_transit_time.py`，用于继续验证路线规划阶段所需的时间数据。

## 🚀 Quick Start

先按 `.env.example` 在项目根目录准备 `.env.local`：

```bash
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseekv4flash
SEARCHAPI_API_KEY=
AMAP_API_KEY=
TAVILY_API_KEY=
BAIDU_APPBUILDER_API_KEY=
```

运行当前主链路示例：

```bash
python3 tools/fetch_webpage_content.py "常州 三日游 攻略" --max-results 5 --output /tmp/guides.md
python3 tools/langgraph_markdown_candidate_pool.py /tmp/guides.md > /tmp/markdown_candidates.json
python3 tools/amap_poi_filter.py /tmp/markdown_candidates.json --json > /tmp/amap_candidates.json
python3 tools/render_geo_day_clusters_map.py /tmp/amap_candidates.json --days 3 --output /tmp/geo_clusters.html
```

工具参数、搜索源接法和 JSON 约定见 [`tools/README.md`](tools/README.md)。

启动后端接口雏形：

```bash
python3 -m pip install -r requirements-backend.txt
python3 -m uvicorn backend.app.main:app --reload
```

当前后端提供：

- `GET /health`：健康检查
- `POST /api/planner/cluster-routes`：接收已带 POI 坐标的候选景点，返回按天聚类后的地图路线占位结构

说明：`cluster-routes` 当前只输出每日景点、访问顺序和空的 `route_segments`，真实高德时间矩阵和路线优化仍在 Roadmap 中。

## 🧱 Architecture

| Layer | Stack / Responsibility |
| --- | --- |
| Agent 编排 | LangGraph / LangChain |
| Agent 测试与迭代 | LangSmith |
| 后端方向 | FastAPI |
| 地图与 POI | 高德地图能力 |
| 信息源 | 网页搜索、攻略正文抓取、markdown 信息源 |
| 规划中间层 | 候选池、POI 坐标补全、地理聚类、通行时间矩阵 |

站点入口约定：

- 官网前台：`www.floattrip.com`
- 用户工作台：`app.floattrip.com`
- 后台管理台：`admin.floattrip.com`

聚类地图目前只是开发阶段的可视化调试工具。正式用户界面计划在前端使用高德地图展示最终规划好的日路线。

## 📁 Project Structure

- `backend/app/main.py`：FastAPI 应用入口，注册健康检查和规划接口
- `backend/app/api/`：后端接口路由，目前包含规划路线预览接口
- `backend/app/schemas/`：请求、POI、地图点位、路线计划和行程文案的数据结构
- `backend/app/workflows/`：规划流程编排入口，目前串联候选景点分天聚类和路线占位响应
- `backend/app/planning/`：确定性规划模块，包含地理分天聚类、路线矩阵和路线优化占位边界
- `backend/app/providers/`：外部服务能力封装，目前抽出高德 POI 公共逻辑
- `backend/app/tools/`：预留给后续 LangGraph / Agent 调用的工具包装层
- `backend/app/agents/`：预留给后续大模型调研和自然语言行程生成的 Agent 边界
- `backend/tests/`：后端 API、聚类迁移和高德 provider 单元测试
- `requirements-backend.txt`：后端运行依赖
- `tools/`：旅行信息搜索、候选池抽取、POI 过滤、聚类兼容入口和调试地图工具
- `tools/README.md`：工具参数、搜索源接法和 JSON 约定
- `static/docs/`：产品 PRD 与前端原型页面
- `static/image/`：官网首页示例图片
- `assets/`：README 和原型使用的早期静态素材

当前后端分层意图：

```text
api        -> 面向前端的接口入口
workflows  -> 串联规划流程
planning   -> 可测试的确定性规划逻辑
providers  -> 高德、搜索、天气等外部服务适配
schemas    -> 前后端和模块之间共享的数据契约
tools      -> 后续给 Agent / LangGraph 调用的工具包装层
agents     -> 后续大模型调研和文案生成边界
```

## 🗺 Roadmap

- 为每天候选景点构建高德通行时间矩阵
- 按通行时间而不是单纯地理距离优化当天访问顺序
- 输出每天可展示在地图上的路线结果
- 把调试链路收敛为正式 Agent、FastAPI 接口和用户工作台流程
