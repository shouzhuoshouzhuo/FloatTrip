# FloatTrip

FloatTrip 是一个旅游规划 Agent 项目。它希望把旅行规划做成一种轻松、顺滑的体验：用户给出目的地、天数和偏好后，系统逐步汇总信息源、筛出真实景点、按区域组织候选点，并继续生成可执行的每日路线与自然语言行程。

## 产品方向

FloatTrip 的产品体验围绕“平静水面上的自然浮动”展开：

- 让旅行需求尽量一键转成可执行行程
- 前端采用现代柔和、水面悬浮感的设计语言
- 用弱分割线和强交互动效降低规划过程的紧绷感

站点入口约定：

- 官网前台：`www.floattrip.com`
- 用户工作台：`app.floattrip.com`
- 后台管理台：`admin.floattrip.com`

## 第一版规划思路

第一版规划 Agent 以查询和定位能力为基础，先把“值得去哪里”做稳，再补上“当天怎么走”：

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

当前候选池排序仍以攻略中景点出现次数为主要信号，后续再逐步引入偏好、营业信息、通行成本和节奏约束。

## 当前进度

仓库目前已经实现了候选景点进入按天区域聚类前后的开发链路：

1. 抓取网页正文并转成 markdown 信息源：`tools/fetch_webpage_content.py`
2. 从 markdown 攻略抽取候选景点池：`tools/langgraph_markdown_candidate_pool.py`
3. 输出候选池 JSON，例如 `/tmp/markdown_candidates.json`
4. 用高德 POI 过滤候选景点并补齐坐标：`tools/amap_poi_filter.py`
5. 输出带 POI 坐标的候选池 JSON，例如 `/tmp/amap_candidates.json`
6. 按地理距离聚类候选点：`tools/geo_day_cluster.py`
7. 渲染聚类调试地图：`tools/render_geo_day_clusters_map.py`

`tools/` 中还保留了百度、Tavily、SearchAPI 等不同搜索入口，以及一个高德公交通行时间脚本 `tools/amap_transit_time.py`，用于继续验证路线规划阶段需要的时间数据。

聚类地图目前只是开发阶段的可视化调试工具。正式用户界面计划在前端使用高德地图展示最终规划好的日路线。

## 快速开始

先按 `.env.example` 在项目根目录准备 `.env.local`：

```bash
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseekv4flash
SEARCHAPI_API_KEY=
AMAP_API_KEY=
TAVILY_API_KEY=
BAIDU_APPBUILDER_API_KEY=
```

下面是一条当前主链路的示例：

```bash
python3 tools/fetch_webpage_content.py "常州 三日游 攻略" --max-results 5 --output /tmp/guides.md
python3 tools/langgraph_markdown_candidate_pool.py /tmp/guides.md > /tmp/markdown_candidates.json
python3 tools/amap_poi_filter.py /tmp/markdown_candidates.json --json > /tmp/amap_candidates.json
python3 tools/render_geo_day_clusters_map.py /tmp/amap_candidates.json --days 3 --output /tmp/geo_clusters.html
```

工具参数、搜索源接法和 JSON 约定见 [`tools/README.md`](tools/README.md)。

## 技术栈

- Agent 编排：LangGraph / LangChain
- Agent 测试与迭代：LangSmith
- 后端方向：FastAPI
- 地图与 POI：高德地图能力

## 仓库结构

- `tools/`：旅行信息搜索、候选池抽取、POI 过滤、聚类和调试地图工具
- `static/docs/`：产品 PRD 与前端原型页面
- `assets/`：README 和原型使用的静态素材
- `web.md`：网页内容抓取和旅行信息源实验材料

## 前端原型

当前仓库仍保留早期静态原型，可直接打开查看：

- `static/docs/preview.html`
- `static/docs/indexv1.html`
- `static/docs/plannerv1.html`

![FloatTrip 示例图](assets/floattrip-demo.svg)

## 下一步

- 为每天候选景点构建高德通行时间矩阵
- 按通行时间而不是单纯地理距离优化当天访问顺序
- 输出每天可展示在地图上的路线结果
- 把调试链路收敛为正式 Agent、FastAPI 接口和用户工作台流程
