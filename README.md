

# ✈️ AI 旅游规划助手

**一句话描述需求，自动生成带时刻表的多日旅游计划**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2+-FF6B35)](https://github.com/langchain-ai/langgraph)
[![Eval: pass@k](https://img.shields.io/badge/Eval-pass%40k%20%2F%20pass%5Ek-brightgreen)](tests/EVAL_GUIDE.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>


---

## 📖 简介

AI 旅游规划助手是一个基于 **LangGraph 多 Agent 流水线** 的旅游行程生成工具。只需输入一句话的出行需求（目的地、日期、偏好），系统即可自动完成：

- 🔍 **意图识别（快速失败）** — 从自然语言抽取目的地、日期、偏好；支持"明天开始3日游"等相对时间 + 天数表达式；缺目的地/日期时立即返回，不触发后续 LLM 调用
- 🌤️ **天气感知** — 自动拉取出行日期天气预报，雨雪天优先安排室内景点，超出预报范围时降级提示
- 🗺️ **景点搜索** — 调用高德地图 API 获取真实景点候选池，按评分过滤
- 🧭 **智能规划** — Planner/Reviewer 多轮循环优化，共享对话记忆确保紧急问题优先修复
- 🍜 **餐饮推荐** — 基于每天动线搜索周边餐厅，按天并行调用 LLM 推荐午晚餐
- 🗺️ **地图可视化** — 前端接入高德 JS API，在半屏地图上逐天绘制行程动线与景点标注
- ✍️ **手动编辑** — 对生成的行程可拖拽换序、搜索换点/换餐厅、改时段，带撤销/重做栈；保存时服务端重算逐段距离
- 🔌 **多 LLM 提供商** — 通过 `LLM_PROVIDER` 一键切换 DeepSeek / 豆包，统一工厂函数封装，缺 Key 时给出明确报错

所有景点与餐厅数据均来自**高德真实 POI**，不会凭空捏造地点。

> 🧪 **这个项目有Agent评测体系**：基于 Anthropic《Demystifying Evals for AI Agents》方法论，对核心 Agent（Planner / Reviewer）建立了可复现的定量评估框架，包括代码打分器 G1–G7 + LLM 评委 + Reviewer 可靠性指标，指标覆盖 pass@k、pass^k、收敛轮次、误放行率、planner 反驳率。详见 [`tests/EVAL_GUIDE.md`](tests/EVAL_GUIDE.md)。

---

## 🎬 演示

> 新建规划页

<p align="center">
  <img src="./static/images/规划页.png alt="规划页" width="900" />
</p>

> 规划进度页

<p align="center">
  <img src="./static/images/规划进度.png" alt="详情页" width="900" />
</p>

> 规划详情页

<p align="center">
  <img src="./static/images/规划详情.png" alt="详情页" width="900" />
</p>

> 历史规划页

<p align="center">
  <img src="./static/images/历史行程页.png" alt="历史页" width="900" />
</p>

> 我的画像

<p align="center">
  <img src="./static/images/我的画像.png" alt="历史页" width="900" />
</p>


---

## 🏗️ 架构

```
用户输入
   │
   ▼
[Intent Agent]  ──── 缺少目的地/日期 ──→  提示补充信息（快速失败，无额外 LLM 成本）
   │
   ▼
[Query Rewrite]  ←── 直接读 DB 画像，单次 LLM 改写 + 冲突解析（登录用户专属）
   │
   ▼
[高德景点搜索]  ←── 多关键词 + 评分过滤
   │
   ▼
[Planner Agent] ──────────────────────────┐
   │                                      │
   ▼                                      │ 评审不通过（最多 N 轮）
[Reviewer Agent] ─────────────────────────┘
   │ 通过 / 达上限
   ▼
[Time Check Agent] ←──────────────────────┐
   │                                      │ 有时间冲突（最多 M 轮）
   │ 无冲突 / 达上限                      │
   │                              [Planner Agent]（仅修正时间）
   ▼
[高德周边餐饮搜索]（1000m 内）
   │
   ▼
[Meal Recommend Agent]
   │
   ▼
[Finalize]  →  含时刻表 + 餐厅 + 距离的完整行程
```

**修改规划（迷你图）**：用户对已有行程提修改意见时，跳过 Intent/景点搜索，从上次规划的 checkpoint 恢复状态，只跑 `Planner ⇄ Reviewer（最多 2 轮）→ 餐饮 → Finalize`，Reviewer 验证 Planner 是否真正响应了修改意见（修改流程不接入 Time Check）。

**技术栈**


| 层        | 技术                                |
| -------- | --------------------------------- |
| 后端框架     | FastAPI + Uvicorn                 |
| Agent 编排 | LangGraph                         |
| LLM      | DeepSeek / 豆包（`LLM_PROVIDER` 切换，LangChain OpenAI 兼容层） |
| 地图数据     | 高德地图 Web 服务 API                   |
| 前端       | JSX 组件化单页（无构建，浏览器内 Babel）         |


---

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/your-username/trip-agent.git
cd trip-agent
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env.local
```

编辑 `.env.local`，填入你的 API Key：

```env
AMAP_API_KEY=your_amap_key             # 高德 Web 服务 Key（必填，景点/天气）
LLM_PROVIDER=deepseek                  # LLM 提供商（可选，deepseek/doubao，默认 deepseek）
DEEPSEEK_API_KEY=your_deepseek_key     # DeepSeek API Key（用 deepseek 时必填）
DOUBAO_API_KEY=your_doubao_endpoint    # 豆包 endpoint ID（用 doubao 时必填）
AMAP_JS_KEY=your_amap_js_key           # 高德 JS API Key（可选，前端地图）
AMAP_JS_SECURITY_CODE=your_js_secret   # 高德 JS API 安全密钥（可选，与 JS Key 配套）
REDIS_URL=redis://localhost:6379/0     # Redis 缓存（可选，不填则跳过缓存，不影响功能）
```

> 多 LLM 提供商的详细配置、切换方式与故障排查见 [`LLM_PROVIDERS.md`](LLM_PROVIDERS.md)。

> **如何获取 Key？**
>
> - 高德 Web 服务 Key：登录 [高德开放平台](https://lbs.amap.com/) → 控制台 → 创建应用 → 添加 **Web 服务** Key
> - 高德 JS API Key：同一应用下再添加一个 **Web 端 (JS API)** Key，并配置安全密钥 `securityJsCode`（前端地图可视化用，不填则地图区域降级提示）
> - DeepSeek Key：登录 [DeepSeek 开放平台](https://platform.deepseek.com/) → API Keys

### 4. （可选）启动 Redis

如需启用缓存，先启动 Redis，再配置 `REDIS_URL`：

```bash
# macOS
brew install redis && brew services start redis

# Docker
docker run -d -p 6379:6379 redis:alpine
```

不启动也完全可以正常使用，缓存功能会自动跳过。

### 5. 启动服务

```bash
python run.py
```

打开浏览器访问 **[http://localhost:8765](http://localhost:8765)**，输入出行需求即可。

---

## 📁 项目结构

```
├── app/
│   ├── core/          # 环境变量加载、HTTP 工具、Redis 缓存层、SQLite、记忆、鉴权
│   ├── api/           # 路由模块（auth/history/profile/plan，各带 prefix）
│   ├── llm/           # LLM 工厂：factory.py（按 LLM_PROVIDER 分发）+ deepseek.py / doubao.py
│   ├── providers/
│   │   ├── amap/      # 高德地图 POI 搜索
│   │   └── weather/   # 高德天气预报
│   └── planning/
│       ├── schemas.py  # Pydantic 数据模型 & LangGraph 状态
│       ├── nodes.py    # 各 Agent 节点函数
│       ├── graph.py    # LangGraph 图构建与流水线入口
│       ├── helpers.py  # 纯工具函数（地理计算、评审预检等）
│       └── prompts.py  # 所有 LLM System Prompt
├── tests/
│   ├── EVAL_GUIDE.md              # 评估框架使用手册
│   ├── eval/                      # Planner/Reviewer 评估框架
│   │   ├── harness.py             # fixture → TravelPlanState → mini-graph
│   │   ├── run_eval.py            # 主入口：加载用例 → k 次评估 → 报告
│   │   ├── report.py              # 指标聚合与 Markdown 报告
│   │   ├── capture_pool.py        # 调高德 API 抓真实景点池骨架
│   │   ├── generate_fixtures.py   # 批量生成测试 fixture
│   │   └── graders/
│   │       ├── code_graders.py    # G1–G7 确定性代码打分器
│   │       ├── llm_judge.py       # LLM 评委（主观维度打分）
│   │       └── reviewer_reliability.py  # Reviewer 可靠性 + Planner 反驳率
│   ├── eval_query_rewrite/        # query_rewrite 节点专项评估
│   │   ├── fixtures.py            # 5 个测试场景（补全/冲突/不发明）
│   │   ├── harness.py             # 直接读 DB + 单次 LLM 调用 + 确定性打分
│   │   └── run_eval.py            # 评估入口：--only / --k / --out
│   └── test_weather_mock.py       # 雨天 mock 冒烟测试
├── frontend/          # JSX 组件化单页（main/pages/components/mascot/tweaks-panel/edit/api）
├── run.py             # 启动入口
└── .env.example       # 环境变量模板
```

---

## 🔑 设计亮点

**1. 候选池封闭世界约束**
所有景点必须来自高德 API 搜索结果，LLM 不得凭空生成景点名。Reviewer Agent 有硬性检查，出现非候选池景点直接打回重规划。

**2. 代码评审 + LLM 评审分层**
Reviewer 的判断依据由 Python 预先计算（每天地理跨度、开放时间冲突检测），以客观事实形式喂给 LLM，避免纯 LLM 评审的幻觉风险。

**3. Planner-Reviewer 共享对话记忆**
每轮规划双方各追加一条记录到 `planner_reviewer_dialogue`。Reviewer 凭此记住自己上轮标注的【紧急必须优先改】是否已被响应，避免每轮从零审视导致的低效循环；Planner 也能对照哪些意见已修复、哪些紧急问题仍待解决。

**4. 天气感知路线规划**
Intent 阶段自动拉取高德天气预报（复用已有 `AMAP_API_KEY`），将天气信息注入 Planner 和 Reviewer 的 prompt。雨雪天 Planner 会优先安排博物馆、展馆等室内景点，Reviewer 也会检查路线是否与天气矛盾并打回修改。超出预报范围（约 4 天）时降级提示，不中断规划流程。

**5. 餐饮推荐按天并行 + 确定性降级**
将原本"所有天一次 LLM 调用"改为每天独立调用（`SingleDayMealPick`，4 字段），不同天用线程池并行执行，单天 LLM 失败时自动降级取评分最高餐厅，不影响其他天，彻底消除因 prompt 过长导致的 500 错误。

**6. 结构化输出防护**
所有 LLM 调用通过 `invoke_structured` 包装，对 DeepSeek function calling 偶发返回 `None` 的情况自动重试，保证流水线稳定。

**7. 前端地图动线可视化**
后端通过 `GET /api/config` 仅向前端下发高德 **JS API** 密钥（不暴露敏感的 REST `AMAP_API_KEY`），前端按天用高德地图绘制景点标注与连线动线，地图占据半屏，未配置 JS Key 时地图区域降级为友好提示，不影响行程文本展示。

**8. Time Check 专项 Agent（开放时间二次修正循环）**
主流程 Planner-Reviewer 循环结束后，新增 `time_check` 节点专门核查每个景点的安排时段是否与开放时间/闭馆日冲突。它使用 CoT 推理（先写完整逐景点推理过程，再从结论中筛选违规），输出定向修正指令交给 Planner 修正，最多循环 `max_time_check_rounds` 轮（默认 3）。开放时间问题完全由该 Agent 处理，Reviewer 不再涉及，避免双重干预震荡。

**9. Reviewer 职责精简 + 友好提醒机制**
Reviewer 不再负责开放时间检查（交给 Time Check）。`RouteReview` schema 拆成两个输出字段：`route_modify_opinion`（技术诊断，给 Planner 看）和 `issues`（友好出行提醒，给用户看，禁止"违规/冲突"等批判词）。`day_proximity_report` 增加跨天中心间距计算，不足 5km 时自动标注⚠️，客观检测多天行程在同一区域反复横跳的问题。

**10. Redis 缓存层（可选，优雅降级）**
高德天气（TTL=4h）和 POI 搜索（TTL=12h）结果自动写入 Redis，重复请求直接命中缓存。`REDIS_URL` 未配置或 Redis 不可用时，`cache.py` 静默降级为透传，整个功能无任何副作用，不影响主流程稳定性。

**11. 路线优化（暴力枚举最短路径）**
规划完成后，用户可对任意一天点击"优化路线"：后端枚举 daytime 景点全排列，**路程目标只计算景点（daytime + evening）之间的 haversine 距离，餐厅不参与评分**（避免被就餐点位置干扰真实游玩动线），evening 景点固定末位，重算每段 `dist_from_prev_km` 并时间槽顺序对齐后写回 DB。原始排列也在候选内，保证 `best_km ≤ original_km`；若优化距离与原始差距 < 0.05 km 则标记 `improved=false`。支持一键回退到 Agent 原始顺序（`POST /api/plan/revert_day`），前端在首次优化时保存原始 timeline 快照，确保回退数据准确。

**12. 地理分区聚类（替代坐标盲的行政区名）**
喂给 Planner/Reviewer 的候选池不再只标行政区名（adname）——同一行政区的景点可能相距很远（如玄武湖与中山陵同属玄武区却约 10km）。`cluster_pois_by_location` 用真实经纬度做确定性 k-means（按出行天数定 k，固定种子初始化保证可复现），把候选池按『📍地理分区』分组展示，并在 prompt 中明确"行政区相同不代表距离近，以地理分区为准"，引导模型把同区景点排进同一天、减少跨城横跳。

**13. 手动编辑行程（拖拽 / 换点 / 改时段 + 服务端重算）**
生成的行程支持进入编辑态手动调整：SortableJS 拖拽换序（时段留在位置上不跟卡走）、调起高德搜索弹层更换或新增景点/餐厅（`GET /api/poi/search` 代理，入参清洗 + 长度限制）、直接编辑每段时间，带完整撤销/重做栈与 `beforeunload` 离开守卫。保存走 `PUT /api/plan/{id}/timeline`，**服务端按 haversine 重算每段 `dist_from_prev_km` 为准**（前端实时显示用同公式但不落库），并对残缺 location 做防御避免 KeyError。

**14. 偏好占位垃圾值清洗**
LLM 在用户未提供偏好时偶尔吐出 `null`/`none`/`无`/`不限` 等占位垃圾值。`clean_pref` 仅在『整串』等于垃圾 token 时归一为"无偏好"（None），避免误伤"无辣不欢"这类正常偏好，统一作用于 intent 抽取与 query_rewrite 输出。

---

## 🧪 评测体系

> **为什么信任这个系统的输出质量？**

本项目参照 Anthropic《Demystifying Evals for AI Agents》的方法论，对 Planner 和 Reviewer 两个核心 Agent 建立了一套**可复现的定量评估框架**。

### 评估设计

```
冻结输入（fixture）           真实 LLM 调用
 景点池 + 天气              Planner ⇄ Reviewer
    │                            │
    └──── mini-graph ────────────┘
                │
           最终 route
                │
     ┌──────────┴──────────┐
     ▼                     ▼
代码打分器 G1–G7        LLM 评委（主观维度）
（确定性，零 LLM 成本）   （偏好/节奏/天气适配）
```

- **输入冻结**：每个测试用例（fixture）冻结了景点候选池和天气，跳过 intent / 高德搜索，使评估可复现、零额外 API 成本
- **代码打分器 G1–G7**：复用代码（`helpers.py`）对最终路线做确定性校验，涵盖封闭池、开放时间、地理跨度、结构合法性、天气合规等
- **LLM 评委**：对主观质量（偏好贴合、节奏、动线连贯、天气应对策略）打 1–5 分
- **Reviewer 可靠性**：统计误放行率（放过坏方案）和误打回率（拒绝好方案），量化 Reviewer Agent 本身的判断质量
- **Planner 反驳率**：逐轮分析 Planner 对 Reviewer 意见的响应（采纳 / 反驳 / 忽略），忽略率高是 pass 率低的强信号

### 核心指标

| 指标 | 含义 |
|---|---|
| **pass@k** | k 次中≥1 次客观通过且收敛（能力下界） |
| **pass^k** | k 次全部通过（稳定性） |
| **轮次均值** | 平均用几轮收敛，目标 ≤ 3 |
| **误放行率** | Reviewer 放过不合格方案的概率，理想接近 0% |
| **忽略率** | Planner 对 Reviewer 意见不改也不解释，越低越好 |

### 快速运行

```bash
# 单用例冒烟（不调 LLM 评委，省钱）
python -m tests.eval.run_eval --only nanjing-3d-sunny-history --k 1 --no-judge

# 标准评估（k=5，输出 Markdown 报告）
python -m tests.eval.run_eval --k 5 --out eval_report.md
```

详细说明见 [`tests/EVAL_GUIDE.md`](tests/EVAL_GUIDE.md)。

### query_rewrite 节点专项评估

针对 `query_rewrite` 节点的行为验证，独立于 Planner/Reviewer 评估框架，位于 `tests/eval_query_rewrite/`。

**测试的三个核心行为：**

| 指标 | 含义 |
|---|---|
| **g_supplement** | query 无偏好时，应从历史画像补全对应字段 |
| **g_conflict** | query 与画像冲突时（如"不吃辣" vs 画像"辣味美食"），以 query 为准 |
| **g_no_invention** | query 和画像均无偏好时，三字段应为 null，不凭空编造 |

**5 个 fixture 覆盖场景：**`no-pref-supplement` / `conflict-food-query-wins` / `partial-merge` / `empty-profile` / `no-pref-both`

```bash
# 单用例冒烟（最快）
python -m tests.eval_query_rewrite.run_eval --only conflict-food-query-wins

# 全量 5 用例
python -m tests.eval_query_rewrite.run_eval

# 稳定性（每用例跑 3 次）
python -m tests.eval_query_rewrite.run_eval --k 3 --out qr_eval_report.md
```

---

## 📄 License

[MIT](LICENSE)