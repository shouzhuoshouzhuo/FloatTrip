# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

AI 旅游规划助手。FastAPI 后端运行 **LangGraph 多 Agent 流水线**，将一句话出行需求转化为带时刻表的逐天行程（含景点、天气适配、餐厅推荐），LLM 使用 **DeepSeek**，地图数据使用**高德 REST API**。前端为原生 JS 静态页面。代码注释、prompt、用户界面均为中文。

## 常用命令

```bash
pip install -r requirements.txt   # 安装依赖
python run.py                     # 启动服务 http://localhost:8765
python -m tests.test_weather_mock # 运行雨天 mock 测试（无侵入式）
```

无测试框架、无 lint、无前端构建步骤。`tests/` 已加入 `.gitignore`。

**环境变量**：配置在 `.env.local`（参考 `.env.example`）。必填：`AMAP_API_KEY`、`DEEPSEEK_API_KEY`。可选：`DEEPSEEK_MODEL`（默认 `deepseek-v4-flash`）、`HTTPS_PROXY`。环境变量统一通过 `app/core/env.py::load_local_env` 加载，不要在其他地方散读。

## 架构

### 请求流
`POST /api/plan`（`app/main.py`）→ `app/planning/graph.py::run` → 返回 `{success, missing_fields, history, plan}`。路由同步执行，FastAPI 自动放线程池。静态前端挂载在 API 路由**之后**（顺序不能颠倒）。

### LangGraph 流水线

```
START → intent ──(缺目的地/日期)──→ END
              └→ attraction_search → planner → reviewer
                                       ↑           │
                                       └───────────┘  # 循环直到通过或达 max_review_rounds
                                                   └→ meal_search → meal_recommend → finalize → END
```

状态载体是 `TravelPlanState`（`schemas.py`），Pydantic 模型，节点返回**部分 dict** 由 LangGraph 合并。

- **intent**：抽取目的地/日期/偏好；`travel_days` 字段支持从"3日游"推算结束日期；日期确定后自动拉取高德天气预报（`app/providers/weather/amap.py`，约 4 天，超范围降级处理）；缺字段时写入 `missing_fields` 并提前终止。
- **attraction_search**：高德关键字搜索，按 `min_rating` 过滤，构建**封闭候选池**——后续所有 Agent 只能引用池内景点名。
- **planner ⇄ reviewer 循环**：Planner 生成带时刻表的路线时需考虑天气（雨雪天优先室内景点）；Reviewer 基于 Python 预计算的客观事实（地理跨度、开放时间、候选池校验）+ 天气评审，`unknown_spots` 硬性打回。循环上限 `max_review_rounds`，最后一轮 issues 写入 `state.reviewer_issues`。
- **meal_search → meal_recommend**：以每天最后一个上午/下午景点为中心搜周边餐厅，LLM 选午晚餐；午晚餐重复时有确定性兜底逻辑（`nodes.py`）。
- **finalize**：拼装 `final_plan`，插入餐厅、照片、开放时间、haversine 距离，以及 `weather_forecast`、`weather_note`、`route_issues`。

### 重要约定

- **LLM 调用必须走 `invoke_structured`**（`helpers.py`）：DeepSeek function calling 偶发返回 `None`，该函数自动重试，避免 `AttributeError`。
- **景点匹配用名称字符串**，不用对象引用——LangGraph 序列化后对象 identity 失效。
- **Prompt 集中在 `prompts.py`**，Agent 行为逻辑在 prompt 和节点代码中各占一半，修改时两处要同步。
- 调参入口：`PlanRequest` 的 `max_per_day`、`min_rating`、`max_spots`、`max_review_rounds`、`model_name`，通过 `**overrides` 注入 `TravelPlanState`。
- 各节点 LLM 通过 `make_*_node(model_name)` 工厂构建，温度：intent/reviewer/meal = 0，planner = 0.3。
