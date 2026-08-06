## Why

当前 Chat 只在每轮请求中拼接有限数量的历史消息，且长对话查询会在 200 条后错误地停留在旧历史；LangGraph checkpoint 又以 `run_id` 隔离，不能承担一次 Conversation 的跨轮记忆。现有四列表画像缺少来源、纠正、作用域和敏感信息保护，也无法为长会话提供稳定的冻结快照。

## What Changes

- 以 `conversation_id` 建立持久短期记忆状态，在首条消息时冻结长期记忆快照，并按明确优先级组装真实角色消息。
- 按可配置 token 预算把长会话压缩为结构化累计摘要和最近完整轮次，压缩前持久化长期记忆提取任务。
- 在 Chat 页提供主动压缩入口，复用相同安全边界且始终保留原始消息。
- 引入带来源、作用域、敏感级别、候选状态和替代关系的旅游结构化记忆事实，并停止使用四列表画像作为权威存储。
- 增加显式会话归档、异步最终记忆归并、失败重试以及归档后只读语义。
- 重做画像页，使用户能够查看、确认、编辑和遗忘结构化记忆。
- **BREAKING**：画像 API 从四个字符串数组改为事实与候选集合；旧 `user_profiles` 仅作为迁移备份，不再读写。

## Capabilities

### New Capabilities

- `conversation-memory`: 会话级冻结快照、真实消息组装、token 预算和结构化摘要行为。
- `travel-memory-facts`: 旅游领域长期事实的提取、作用域、纠正、敏感信息保护和规划注入。
- `memory-lifecycle-management`: 会话归档、异步提取任务、画像管理 API 与用户界面。

### Modified Capabilities

无。

## Impact

- 数据库新增会话记忆、用户记忆 revision、记忆事实和提取任务表，并迁移旧画像数据。
- Chat service、Prompt、Runtime 启停、规划 Run 快照、Profile/Conversation API 和前端画像/对话界面均受影响。
- 不改变 `run_id` checkpoint 隔离、不增加会话 TTL、不清理 Run event，也不引入多节点任务调度。
