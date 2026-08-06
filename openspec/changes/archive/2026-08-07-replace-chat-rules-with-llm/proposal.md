## Why

当前旅行对话页允许用户自由输入自然语言，但正式规划需求仍由关键词和正则表达式识别，导致“明天南京3日游”这类清晰表达被错误判断为缺少目的地。系统需要让界面承诺的自然对话能力与后端真实能力一致，由 LLM 统一理解每条用户消息，并彻底移除规则匹配式意图分类和字段抽取。

## What Changes

- **BREAKING**：删除 Chat Graph 中基于关键词、正则表达式和固定句式的意图分类、目的地/天数/日期/预算/偏好抽取，以及对应的规则回退路径。
- 新增单一的结构化 Dialogue Agent，使每条普通 conversation message 都由 LLM 结合当前日期、最近对话、活动 PlanningBrief、关联 Run 和目标 itinerary 上下文进行理解。
- 使用受限的结构化输出同时返回意图、用户可见回复、PlanningBrief 增量、关联目标、澄清问题和确认要求。
- 由确定性策略层校验结构化输出、日期一致性、资源归属、状态转换和幂等性；策略层不得重新使用文本规则推断用户语义。
- 当模型调用、结构化解析或校验失败时，执行一次结构化修复；仍失败则公开返回可重试错误，不得使用正则降级、伪造缺失字段或产生业务副作用。
- 保留正式规划的显式确认边界：LLM 可以理解“开始规划”等表达，但只有通过服务端状态与幂等校验后才能提交 PlanningBrief 或操作 Run。
- 以真实中文自然语言评测集替换规则单元测试，覆盖省略介词、多轮补充、纠正、咨询与规划区分、行程修改、任务控制及多目标歧义。

## Capabilities

### New Capabilities

- `llm-dialogue-understanding`: 定义 LLM 作为唯一自然语言理解来源，统一识别旅行咨询、普通聊天、创建/补充规划、修改行程、任务控制和不确定输入，并产生严格结构化结果。
- `validated-dialogue-actions`: 定义结构化理解结果进入 PlanningBrief、Conversation、Run 和 Revision 之前的确定性校验、显式确认、资源绑定、幂等执行与失败语义。

### Modified Capabilities

无。

## Impact

- 主要影响 `app/chat/graph.py`、`app/chat/service.py`、Chat runtime worker 注册、LLM factory 调用方式和聊天相关测试。
- 新增 Pydantic 结构化输出 schema、Dialogue Agent prompt、结构化调用/修复逻辑和面向自然表达的评测样例。
- Conversation Message、PlanningBrief、Run、Revision 与 SSE 公共事件协议继续作为持久化与前端状态来源；现有前端无需重新引入规则解析。
- 每条普通 conversation message 将产生一次 LLM 理解调用，模型不可用时对话理解能力会明确失败而不是降级猜测。
