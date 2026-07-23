## Context

旅行对话目前由 `app/chat/graph.py` 中的关键词列表、正则表达式和固定句式完成意图分类与 PlanningBrief 字段抽取。普通咨询才交给 LLM 生成回复；正式规划消息则由代码模板回答。`app/chat/service.py` 还会在运行 Chat Graph 前依据控制关键词预绑定 Run，或在存在 `related_itinerary_id` 时直接创建 Revision。这些路径使同一个对话框实际上存在多套语言理解逻辑，也使自然表达的覆盖范围取决于规则枚举。

现有 Conversation、Message、PlanningBrief、Run、Revision、不可变请求快照和 SSE 事件协议继续作为可信状态源。新设计需要一次性切换到 LLM 理解，不采用影子模式，不保留基于文本规则的识别回退，同时继续遵守资源归属、确认、幂等和运行状态约束。

## Goals / Non-Goals

**Goals:**

- 让单一 LLM Dialogue Agent 成为 conversation message 的唯一自然语言理解来源。
- 以严格结构化结果统一表达普通问答、创建/补充规划、确认规划、修改行程、任务控制和澄清。
- 支持省略介词、口语、省略主语、多轮补充与纠正，而不依赖固定句式。
- 将语言理解与业务执行分离：LLM 提议语义动作，服务端校验并执行。
- 在模型或结构化输出失败时明确失败且可重试，绝不回退到规则猜测。
- 直接切换并删除旧规则实现及其规则覆盖测试。

**Non-Goals:**

- 允许 LLM 直接访问数据库、调用任意内部 API 或绕过业务校验。
- 让 LLM 自行决定资源归属、Run 状态转换或幂等语义。
- 改写正式旅行规划 LangGraph 的景点搜索、路线编排、评审和结果生成质量。
- 暴露 chain-of-thought、内部 prompt、原始图状态或模型调试内容。
- 保留旧正则分类器作为 fallback、兼容分支、隐藏开关或影子比较器。

## Decisions

### 1. 使用一个结构化 Dialogue Agent 取代分类节点与抽取节点

Chat Graph 收敛为单一 `dialogue_agent` 语义节点。该节点使用 Pydantic schema 约束模型输出，至少包含：

- `intent`：`travel_qa`、`general_chat`、`create_plan`、`update_brief`、`confirm_plan`、`modify_itinerary`、`run_control` 或 `unclear`；
- `reply`：面向用户的简洁自然语言回复；
- `brief_patch`：目的地、起止日期、天数、预算和偏好的可选增量；
- `target`：模型从所给上下文中选择的 `run_id`、`itinerary_id` 或空值；
- `run_action`：受限的停止、重试或空动作；
- `clarification`：字段、问题和可选候选项；
- `requires_confirmation`：业务动作是否仍需用户确认。

普通问答的最终回答也由同一次调用生成，避免先分类再调用第二个模型。Chat Graph 不再读取关键词列表、执行文本正则或根据固定句式走条件边。

备选方案是“LLM 分类 + 独立 LLM 回复/抽取”，但它增加调用次数并可能产生分类与回复不一致；也不符合单一理解来源的目标。

### 2. 上下文由服务端显式组装且保持有界

`chat_input` 为 Dialogue Agent 提供：

- 当前日期和 `Asia/Shanghai` 时区；
- 当前用户消息；
- 最近一段有界 Conversation Message 历史；
- 当前活动 PlanningBrief 的规范化数据、状态与缺失字段；
- 当前对话中相关 Run 的 ID、类型、公开状态、目的地和结果 itinerary ID；
- 用户通过 UI 明确绑定的 `related_run_id` 或 `related_itinerary_id`；
- 被绑定 itinerary 的权威摘要和版本信息。

上下文只提供执行判断所需的公开、结构化事实，不提供内部 prompt、模型推理、其他用户资源或完整 planner checkpoint。模型只能引用上下文中真实出现的资源 ID。

备选方案是让 Agent 按需查询数据库工具，但这扩大了模型权限和测试面；当前资源集合较小，由服务端一次性组装更安全、更可重复。

### 3. LLM 提议动作，确定性执行器负责状态转换

Dialogue Agent 的输出先经过 schema 校验，再交给 `DialogueActionExecutor`。执行器只依据结构化字段和权威资源状态工作，不重新解析原始文本。

执行映射为：

- `travel_qa` / `general_chat`：持久化 `reply`；
- `create_plan` / `update_brief`：合并并校验 `brief_patch`，发布 PlanningBrief 事件；
- `confirm_plan`：检查 ready brief、明确确认和幂等键后提交正式 Run；
- `modify_itinerary`：校验 itinerary 所有权和唯一目标后创建 Revision；
- `run_control`：校验 Run 所有权、允许的状态和具体 `run_action` 后执行或生成确认动作；
- `unclear` 或带 `clarification`：只持久化追问，不产生其他业务副作用。

日期范围、天数一致性、资源归属、状态机和幂等检查属于业务验证，不属于语言识别。执行器不得包含用于判定 intent、目的地、偏好或动作的关键词、正则或固定句式。

### 4. 移除提交消息前的文本预路由

`ChatService.submit_message` 只负责校验显式传入的资源引用、保存用户消息并创建 Chat Run。它不得再通过 `control_text`、关键词或 Run 数量提前决定语义，也不得因为传入 `related_itinerary_id` 就绕过 Dialogue Agent 直接创建 Revision。

显式 UI 绑定会成为 Agent 上下文和执行器约束，而不是隐式执行指令。若模型判断为修改但没有唯一目标，执行器返回结构化澄清；若模型判断只是询问已绑定行程的问题，则仍作为普通回答处理。

### 5. 结构化修复最多一次，之后显式失败

首次模型结果无法通过 Pydantic 或业务前置校验时，系统使用相同 schema 和精简校验错误发起一次结构化修复。第二次失败时：

- Chat Run 进入可重试的 failed 状态；
- 发布净化后的公开错误，例如“这条消息暂时没有理解成功，请重试”；
- 保留原始用户消息；
- 不更新 brief、不创建 Revision、不控制 Run；
- 不执行任何正则或本地语义 fallback。

重试创建新的关联 Chat Run，并继续使用同一条用户消息快照，避免把失败伪装成缺少字段。

### 6. 确认是业务状态，不由生成文本代替

模型的 `reply` 不能作为确认凭证。正式规划提交只接受两类明确来源：ready brief 上的现有原子提交操作，或校验后的结构化 `intent=confirm_plan`；两者都要求当前 brief 为 `ready`、确认动作未被消费且幂等检查通过。按钮是明确的 UI 命令，不属于自然语言识别，因此无需再次调用 LLM。高影响 Run 控制同样使用结构化动作和权威状态校验。

PlanningBrief 的增量收集和用户明确纠正可立即保存，因为它们仍处于可编辑、未提交状态。最终提交后继续冻结不可变请求快照。

### 7. 测试从规则覆盖改为行为契约与语言评测

删除对关键词列表和特定正则分支的单元测试，新增：

- schema 和执行器单元测试，使用假 LLM 输出，覆盖每个 intent 和所有无副作用失败路径；
- prompt 上下文契约测试，验证 active brief、历史、目标资源和日期被传入；
- 中文自然表达评测集，包含“明天南京3日游”、省略介词、多轮纠正、咨询/规划区分、修改、控制和歧义；
- API/runtime 集成测试，证明模型输出到 PlanningBrief、Run 和 Revision 的状态转换；
- 浏览器回归，验证用户看到自然回复、正确摘要、澄清、确认、失败重试和连续修改。

语言评测断言结构化语义结果和副作用边界，不断言模型内部推理或逐字回复。

## Risks / Trade-offs

- **[每条消息增加一次模型调用，延迟和成本上升]** → 使用一次结构化调用同时完成理解与回复，保持上下文有界，并在 UI 中继续流式展示运行状态。
- **[模型可能输出错误字段或虚构资源 ID]** → schema 拒绝未知字段，执行器只接受上下文中存在且属于当前用户的资源。
- **[没有规则 fallback 时 provider 故障会阻断对话]** → 明确显示可重试失败并保留消息；不以错误业务状态换取表面可用性。
- **[直接切换可能暴露未覆盖表达]** → 合并前以固定评测集、集成测试和真实浏览器流程作为硬门槛，而不是运行期影子模式。
- **[同一次模型调用同时回答和提取可能让回复与结构不一致]** → prompt 要求回复复述结构化事实；最终 UI 摘要始终以服务端已校验状态为准。
- **[模型误判明确确认或任务控制]** → 执行器要求合法状态、唯一目标、结构化动作和幂等条件；不满足时降为澄清而非执行。

## Migration Plan

1. 定义 DialogueDecision schema、prompt、结构化调用与一次修复机制。
2. 实现有界上下文组装和不解析文本的 DialogueActionExecutor。
3. 将 Chat Graph 切换为单一 Dialogue Agent，并接入现有 runtime finalizer 与公共事件。
4. 删除 `ChatService.submit_message` 中的关键词预路由和直接 Revision 快捷路径。
5. 删除旧分类/抽取函数、正则、关键词常量和相应测试。
6. 运行 schema、执行器、runtime、API、评测集和浏览器完整流程测试。
7. 测试门槛全部通过后直接合并启用，不部署影子模式或规则回退。

回滚只能通过回退整个代码变更恢复上一版本；新路径不保留运行期开关。数据库资源结构保持兼容，因此回滚不要求数据迁移。

## Open Questions

- 当前 provider 的结构化输出能力是否足以直接绑定 Pydantic schema，还是需要复用现有 `ainvoke_structured` 修复封装？
- 文本形式的 `run_control` 是否全部先显示确认卡，还是仅停止运行中的任务需要确认？
- 中文语言评测集在 CI 中使用固定假模型契约，还是额外提供需要真实 provider 的手工质量门槛？
