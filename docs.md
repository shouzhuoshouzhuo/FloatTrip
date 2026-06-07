# 在此记录实践中学到的agent开发知识

问题一：Planner 的 notes 与实际 route JSON 不一致
现象：Planner 的对话记录声称"已把 Day5 明孝陵替换为总统府"，但 Reviewer 下一轮仍然报同样的问题，反复循环。

根因：DeepSeek 在生成复杂嵌套 JSON（5天×3景点）时，notes 字段（自然语言说明）和 days 字段（实际 JSON 结构）是同一次调用的两个独立输出，两者可以不一致——结构化输出 hallucination。Reviewer 评审的是 JSON，不是 notes。

修复：

Prompt 约束：在 feedback 块里加硬约束——"notes 说改了但 JSON 未变 = 没改，Reviewer 只读 JSON"。
Spot diff 检测：Planner 节点拿到新 route 后，与上一轮做景点集合 diff，若 notes 描述了改动但景点组成无变化，写 ⚠️ warning 到 history，对话记录里同时附上实际变更摘要。
沉淀：同一次 LLM 调用的不同字段可以相互矛盾（结构化输出 hallucination）。当 "说明字段" 和 "执行字段" 并存时，要在代码层做一致性校验，而不是信任 LLM 的自我描述。Reviewer 或下游模块要明确指定它读的是哪个字段。
2. 跨请求记忆（Intra-Session / Multi-turn）—— missing_fields 中断后无法续接
现有的：缺目的地就直接 END，返回 missing_fields，前端让用户重新输入，整个 graph 从头跑。

缺口在哪：用户第一次说"帮我规划南京"，被问缺日期，他回"3天"，现在是两次完全独立的 POST /api/plan，第二次必须重新搜景点、重新意图识别。

可以加：LangGraph Checkpointer（MemorySaver 或 SQLite）。

改动位置：

# graph.py
from langgraph.checkpoint.memory import MemorySaver
checkpointer = MemorySaver()
return g.compile(checkpointer=checkpointer)

# main.py - 请求带 thread_id
config = {"configurable": {"thread_id": request.thread_id}, ...}
result = app.invoke(init, config=config)
效果：missing_fields 触发时 graph 暂停在 intent 节点之后，第二次请求带同一 thread_id 续跑，attraction_search 只跑一次。这是 LangGraph 的招牌能力，改动只涉及 graph.py 和 main.py 两个文件的十几行。

---

问题三：Agent 要做"按星期判断开放日"的推理，却没拿到旅游日期对应的星期几
现象：Planner 在 notes 里写"德安里开放时间为周三至周日…假设明天为周三至周日中的某一天（可开放日）"——它在**猜**出发那天是星期几，因为 prompt 只给了"旅行天数 3 天"，从没告诉它 Day1/Day2/Day3 各自是几月几号、星期几。

根因：日期信息断在了 intent 节点。intent 算出了 `travel_start_date`（date 对象）存进 state，但下游 planner/reviewer 的 human prompt 只拼了 `state.days`（天数），没把"逐天日期+星期"展开喂给模型。而 Python 侧的客观预检 `open_time_violations` 也只用正则抠 `HH:MM-HH:MM` 时间段、**完全忽略星期/闭馆日**，所以"周一闭馆"这类违规既没进 prompt、也没被代码兜住。

修复（最小、聚焦"把信息喂给 agent"）：
- nodes.py 加 `_travel_dates_block(state)`：从 `travel_start_date + timedelta(i)` 逐天展开成 `Day1 = 2026-06-08（周一）…`（复用已有 `WEEKDAYS` 常量），无出发日期时返回空串降级。
- 注入 planner 和 reviewer 两处 human prompt。
- prompts.py 同步收紧 PLANNER #3 / REVIEWER #4：明确"对照 prompt 给出的星期，别把有闭馆日的景点排在不开放那天 / 排了要打回"（CLAUDE.md 约定：prompt 与节点代码两处同步改）。

沉淀：① "agent 输出在做某种推理，但推理依据它根本没拿到" 是 multi-agent 流水线里很隐蔽的一类 bug——LLM 不会报错，而是悄悄编一个假设继续往下做（这里是"假设明天是开放日"）。排查信号就是 notes/reasoning 里出现"假设/大概/若…则…"。② 状态在节点间是显式传递的：上游算出的字段（date 对象）不会自动变成下游 prompt 文本，要在每个用到的节点手动展开成模型能读的自然语言。③ 客观事实优先用代码预检（确定性、省 token），但当规则太杂（中文开放时间文案"周三至周日""法定节假日除外"千变万化）解析易误判时，退一步"把结构化事实（星期）摆给 LLM 让它自己判断"是更稳的折中——本次没硬写星期闭馆的 Python 校验，正是为避免误打回。

---

## 用户系统 + 长期记忆改造（2026-06-07）

**实现了什么**：为项目加入了用户登录、跨请求长期记忆、多轮续接、修改规划、历史行程页。

### 关键设计决策与沉淀

**1. LangGraph Checkpointer vs 进程内 TTL 字典（多轮续接）**

`missing_fields` 场景下 graph 在 `intent → END` 就终止，`attraction_search`（耗时的高德 API）尚未运行，没有什么昂贵操作需要跳过。用 `SqliteSaver` 是杀鸡用牛刀——实际需要的只是"把第一次的 query 存起来，和第二次的补充合并后重跑"。进程内 TTL 字典（`ThreadStore`，60 行）完全够用，无额外依赖。

沉淀：**在引入框架特性前先问"这个场景真的需要它吗"**。LangGraph Checkpointer 真正有价值的场景是：跨进程恢复、human-in-the-loop 暂停、大量昂贵节点需要跳过。

**2. LangGraph 节点无法直接接收外部依赖（db_conn、user_id）**

节点是 `(state) -> dict` 纯函数，不能加额外参数。解决方案：工厂函数 closure 捕获依赖。`make_finalize_node(memory_writer=None)` 接受一个 callable，`run_stream` 每次请求动态构建 closure 传入。`build_graph()` 每次请求都重新调用（现有代码已如此），无额外开销。

沉淀：**LangGraph 节点的依赖注入模式——工厂函数 + closure**。不要试图把 db 连接塞进 state（会序列化失败），也不要用全局变量（并发不安全）。

**3. SSE StreamingResponse 的 DB 连接生命周期**

`StreamingResponse` 的异步生成器在整个流式过程中持有状态（30-60 秒），不能用 FastAPI `Depends` 注入 DB 连接（generator 返回前依赖不会清理）。方案：在 `gen()` 内用 `memory_writer` closure，closure 在调用时才 `get_conn()`，用完即释放（`contextmanager` 的 `try/finally`），不在 generator 整个生命周期持有连接。

沉淀：**流式响应里的资源管理要细粒度**——不是"请求级别持有"，而是"每次实际写入时获取、立刻释放"。

**4. 修改规划用 Checkpoint + 迷你图，而非重跑全流程**

修改行程让 intent 节点重跑（query="修改行程"）会触发 missing_fields，因为意图识别没有目的地/日期。根本解法：修改模式不该跑 intent → attraction_search → reviewer 全流程，直接用上次规划保存的 planner checkpoint（route/pois/对话记录等）恢复状态，只跑 `planner(1轮) → meal_search → finalize` 的迷你图。

沉淀：**修改/续写类任务用 checkpoint + 专用迷你图**，比重跑全图便宜得多，也不会触发输入校验。checkpoint 存哪里：随 itinerary 一起存 DB（`planner_state_json` 列），load 时带出来直接恢复 `TravelPlanState` 字段。

**5. Human-in-the-Loop 的轻量实现（不依赖 LangGraph interrupt()）**

LangGraph 的 `interrupt()` 需要编译时绑定 checkpointer，且 `astream_events` 里捕获 interrupt 需要额外监听 `on_chain_error` 事件，改动面较大。等价语义的轻量实现：① 在 LLM 输出 schema 里加 `modification_concern` 字段；② agent 完成后检查该字段，非空时存 pending 状态到 DB，向前端 yield `{"type": "modification_warning", ...}` 事件并停止流；③ 前端弹确认框；④ 用户确认后调新端点，加载 pending 状态，续跑 meal_search → finalize；⑤ confirm 后删 pending 记录。

沉淀：**Human-in-the-Loop 的核心是"暂停 + 存状态 + 用户确认后恢复"**，不一定要框架支持。关键是把"中间状态"显式存到外部（DB/Redis），而不是依赖进程内内存——这样前后两次 HTTP 请求可以无缝衔接。LangGraph interrupt 本质也是 checkpointer 存状态，自己实现时思路完全一样。

---

## 问题四：LLM "严格复制" 指令在名称匹配场景下的不可靠性（2026-06-07）

**现象**：餐厅推荐显示"附近暂无餐厅数据"，但用高德 API 手动验证能查到 17-20 家评分 4.0+ 的餐厅，候选数据本身没问题。

**根因**：`meal_recommend` 节点用 `lunch_cands.get(pick.lunch_name)` 做精确字符串匹配。候选喂给 LLM 的名称是 `NEW ARC落日餐厅(玄武湖金陵STYLE店)`，但 LLM 回写时经常省掉分店后缀，返回 `NEW ARC落日餐厅`，导致精确匹配 miss，`lunch_info = None`，最终显示"暂无餐厅数据"。即使 system prompt 写了"餐厅名必须严格复制候选列表写法"，LLM 的实际遵从率也不足 100%。

**修复**：在精确匹配后加子串匹配兜底（名称是候选 key 的子串，或反之），再加"完全 miss → 取评分最高"最终降级：

```python
def _lookup(name, cands_dict, cands_list):
    if name in cands_dict: return cands_dict[name]        # 精确匹配
    for key, val in cands_dict.items():
        if name in key or key in name: return val          # 子串匹配
    return cands_list[0] if cands_list else None           # 降级取最高分
```

**同期 Bug**：`keywords="餐厅"` 只匹配名称含"餐厅"字样的 POI（如"某某餐厅"），绝大多数餐馆（小面馆、火锅店等）都不在其中，实际命中极少。应改用 `types="餐饮服务"` 做分类搜索，与名称无关，覆盖所有餐饮 POI。

**沉淀**：
1. **LLM 的 "严格复制" 指令在精确字符串匹配场景下不可靠**——即使明确要求，也要在代码层做宽容匹配（子串/模糊/最终降级），而不是信任 LLM 100% 遵从。
2. **API 的 keyword 参数 vs type 参数语义不同**：keyword 匹配的是 POI 的名称/描述文本，type 匹配的是 POI 的业务分类。用错参数会静默返回极少结果而没有任何报错，排查时需手动对照 API 文档验证。
3. **"搜索返回正常，但最终显示无数据" 类 bug 的排查路径**：先确认 API 层（有没有结果），再确认解析层（过滤后还剩多少），最后查 lookup 层（精确匹配是否 miss）。本例 API 层和解析层都正常，问题出在 lookup 层。

---

## 问题五：Spot Diff 检测误报——LLM 修改时刻却被误判为"未改动"（2026-06-07）

**现象**：Reviewer 要求调整某景点的结束时间，Planner 正确地把时间从 17:00 改到 17:30，但 history 仍出现 `⚠️ Planner notes 描述了改动，但景点组成无实际变化`。

**根因**：原 spot diff 检测比较的是景点**名称集合**（`{s["name"] for day in route ...}`）。时刻改了但景点名没换，集合相同，误报 warning。只要 Reviewer 的意见是时间类（而非换景点），正常修复也会被标记为"未响应"。

**修复**：改为比较完整 route JSON（`json.dumps(route, sort_keys=True)`）。JSON 包含时刻、顺序、天次分配，任何实质改动都能检测到；只有"完全一字不差"才触发 warning，时间/顺序调整不再误报。

**沉淀**：**用代理指标替代真实指标会产生系统性误报**。"景点名集合相同"是"路线未变"的必要非充分条件。要选最接近真实语义的可测量量——这里就是路线 JSON 本身。当代理指标太粗（只看名字）时，既会漏报（移动景点到不同天），也会误报（只改时刻）。

---

## 问题六：Agent 流水线的快速失败——校验应在最贵操作之前（2026-06-07）

**现象**：用户输入"帮我规划"（缺目的地/日期），系统先跑了 Query Rewrite Agent（ReAct + 多次 LLM 调用查画像），再跑 Intent 才发现缺字段，返回 missing_fields。整个 ReAct 过程白跑了。

**根因**：原图拓扑是 `START → query_rewrite → intent`。query_rewrite 是为了用用户画像丰富 query，让 intent 能提取到更好的偏好；但目的地/日期这两个**硬性必填字段**不依赖画像，原始 query 里有就有、没有就没有，query_rewrite 不会凭空补出来。

**修复**：调换顺序为 `START → intent → query_rewrite → attraction_search`。intent 先跑，发现缺字段立即 END，不触发任何后续 LLM 调用；只有校验通过后，query_rewrite 才运行去注入画像偏好，结果供 planner 用（`state.rewritten_query or state.query`）。

**沉淀**：**Multi-agent 流水线的节点排序原则——校验在前，昂贵操作在后**。把"能快速失败"的节点尽量提前，把消耗大（多次 LLM 调用、外部 API）的节点放在校验通过之后。每个节点都应该问：它的前提条件是否已经被更早的节点验证过？

---

## 问题七：修改规划只过 Planner，没有 Reviewer 把关（2026-06-07）

**现象**：用户提交"第一天景点太多了"的修改意见，Planner 在 notes 里说删了某景点，但实际 JSON 可能把该景点移到了其他天，或者根本没有真正响应意见。没有 Reviewer 兜底，这类"假修改"直接进入最终行程。

**根因**：原修改图是 `planner(1轮) → meal_search → finalize`，完全跳过了 Reviewer。Reviewer 的核心价值——基于客观预检（地理跨度、开放时间、候选池）对 Planner 输出做独立验证——在修改流程里缺失。

**修复**：修改图改为 `planner ⇄ reviewer（最多2轮）→ meal_search → finalize`，复用主流程同一套 `route_after_planner` / `route_after_review` 路由函数，在初始化 state 时注入 `max_review_rounds=2`。`modification_concern`（Human-in-the-Loop 暂停）只在第 1 轮 planner（直接响应用户意见时）触发，后续轮响应 reviewer 反馈时不再弹窗。

**沉淀**：**迷你图（子图）应该保留主流程的质量保证节点**，而不只是最小执行路径。"省一个 LLM 调用"带来的是不受约束的输出，往往得不偿失。迷你图可以裁剪掉输入校验（intent/景点搜索），但不应裁掉输出验证（reviewer）。通过参数控制上限（`max_review_rounds=2`）来平衡质量与成本。

---

## 问题八：用 eval 驱动架构简化——ReAct Agent → 固定工作流（2026-06-07）

**现象**：`query_rewrite` 节点用 ReAct Agent（`create_react_agent`），原始设计意图是让 LLM 自主决定查哪些画像字段。但对 5 个不同场景运行 eval 后，发现 agent 每次的工具调用都是 `input: ['attraction_prefs', 'food_prefs', 'habit_prefs']`——始终一次性查全部三个字段，"自主决定"从未发生。

**根因**：旅行查询场景下，三类偏好（景点/餐饮/习惯）几乎对每次规划都相关，LLM 没有理由跳过任何一类。ReAct 的"自主工具选择"在这个场景下是零收益的——它只是把一个固定行为包了一层不必要的 agent 框架，代价是多了一次额外的 LLM 调用（ReAct loop 本身）。

**修复**：改为固定工作流：直接读 DB 拿全部三字段 → 格式化成 `profile_text` → 单次结构化 LLM 调用（改写 + 冲突解析 + 输出偏好字段）。去掉 `create_react_agent`、`build_chat_deepseek`、`search_user_profile` tool 定义，节省一次 LLM 调用。`QUERY_REWRITE_SYSTEM` prompt 同步从"工具使用说明"改为"直接综合三路输入"的指令。

**沉淀**：
1. **先写 eval，再做架构决策**。"自主工具调用"听起来灵活，但只有 eval 数据能告诉你 agent 实际上是否在利用这个灵活性。如果所有 trace 都是同一个工具调用模式，就说明灵活性是幻觉，固定工作流更合适。
2. **ReAct 适合的场景**：工具集合大、调用哪些工具取决于输入内容（如 web search）。工具集合小且每次都全查时，直接调用比 ReAct 更快、更便宜、更可预测。
3. **eval 的副产品**：为测 ReAct 写的 `tests/eval_query_rewrite/` harness，改为固定工作流后只需删掉 `ToolCallCapture` 和 `g_tool_called`，其余 fixture 和打分器复用不变——eval 框架本身不依赖具体实现，天然支持架构切换验证。

---

## 问题九：`_stage_event` 轮次计算依赖 acc 顺序——`run_modification_stream` 显示第 2 轮（2026-06-07）

**现象**：修改规划时，前端进度显示"正在规划逐日行程（第 2 轮）"，实际上是第 1 轮。

**根因**：`_stage_event` 计算 planner 轮次的公式是 `acc["review_round"] + 1`，设计前提是 **acc 存储节点运行前的状态**（`review_round` 尚未被 planner 递增）。
- `run_stream`（普通规划）在 `on_chain_start` 推事件——节点还没跑，acc 未更新，`review_round=0`，公式得 1 ✅
- `run_modification_stream` 在 `on_chain_end` 推事件，且代码先 `acc.update(upd)`（planner 已把 `review_round` 从 0 写成 1），再调 `_stage_event`，公式得 2 ❌

**修复**：在 `run_modification_stream` 的 planner 分支里，把 `yield _stage_event(...)` 移到 `acc.update(upd)` **之前**。其余节点（reviewer / meal_search 等）update 位置不变。

**沉淀**：**隐式时序假设是跨函数 bug 的温床**。`_stage_event` 的注释里写了"acc 反映节点运行前的状态"，但这个约定只在 `run_stream` 里被遵守，`run_modification_stream` 里用了不同的事件时机（end vs start），悄悄违反了假设。写跨函数共享的计算逻辑时，如果它依赖调用时机，应在注释里明确说明前提，并在所有调用点检查是否满足。

---

## `Field(description=...)` 是写给 LLM 的 prompt，不是代码注释（2026-06-07）

Pydantic `Field(description=...)` 在 LLM function calling 场景下，会被序列化进 JSON Schema 传给模型。这意味着 description 的受众是 LLM，不是 Python 解释器或人类文档读者。

因此，description 里可以用自然语言的上下文引用（如"同上规则"），因为 LLM 读的是整个 schema，上下文是完整的。如果受众是人类文档或代码，"同上"就不够——文档可能被单独引用，代码上下文不一定可见。

同理，description 可以写得像 prompt 片段：约束、规则、示例、边界情况说明，而不是像代码注释那样描述"这个字段是什么"。这是利用 LLM 理解自然语言的能力，而非依赖代码逻辑强制约束输出。