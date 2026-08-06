## ADDED Requirements

### Requirement: Conversation freezes long-term memory
系统 SHALL 在 Conversation 的首条用户消息持久化时冻结该用户当前 active 长期事实和 revision，并在该 Conversation 后续轮次复用同一快照。

#### Scenario: Profile changes during a conversation
- **WHEN** Conversation 已有冻结快照且用户长期事实随后发生变化
- **THEN** 当前 Conversation 继续使用原 revision，新 Conversation 使用最新 revision

### Requirement: Prompt preserves role and memory precedence
系统 SHALL 按静态系统规则、动态时间、冻结记忆、会话摘要、权威应用状态、最近真实消息和当前消息的顺序构造模型输入，并 SHALL 让当前消息覆盖更旧的记忆内容。

#### Scenario: Current correction conflicts with frozen memory
- **WHEN** 冻结记忆表示用户爱吃辣而当前消息明确表示不吃辣
- **THEN** Chat 按当前纠正理解本轮且不在当前 Conversation 中刷新冻结快照

### Requirement: Long conversations are compressed by token budget
系统 SHALL 在估算输入超过配置阈值时，把完整旧轮次压缩为结构化累计摘要，并保留配置数量的最近完整轮次。

#### Scenario: Context crosses the summary threshold
- **WHEN** 待组装上下文超过 2600 个估算 token
- **THEN** 系统先持久化对应范围的提取任务，再在 AssistantMessage 边界更新摘要和压缩游标

#### Scenario: Summarization fails
- **WHEN** 摘要模型调用或结构校验失败
- **THEN** 系统保留旧摘要和全部原始消息，并使用预算内最新消息继续 Chat

### Requirement: Message history uses the newest rows
系统 MUST 从数据库获取真正最新的历史消息，并以正序提供给模型。

#### Scenario: Conversation exceeds two hundred messages
- **WHEN** Conversation 已有超过 200 条消息
- **THEN** 模型上下文包含最新历史而不是第 200 条之前的旧窗口

### Requirement: Users can explicitly compress an active conversation
系统 SHALL 允许用户主动触发一次安全的累计摘要压缩；该操作 MUST 保留配置数量的最近完整轮次、MUST 在压缩前持久化提取任务，并 MUST 保留全部原始消息。

#### Scenario: Manually compress a conversation with old complete turns
- **WHEN** active Conversation 的完整轮次数量超过保留轮数且用户点击主动压缩
- **THEN** 系统在 AssistantMessage 边界推进摘要游标、返回压缩范围，并保持最近完整轮次为原始消息

#### Scenario: Manually compress a short conversation
- **WHEN** Conversation 只有配置保留数量以内的完整轮次
- **THEN** 系统返回无需压缩且不调用摘要模型

#### Scenario: Manually compress an archived conversation
- **WHEN** 用户尝试主动压缩 archived Conversation
- **THEN** 系统返回 `409 conversation_archived`
