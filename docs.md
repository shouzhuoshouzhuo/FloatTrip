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