## Why

结构化长期记忆已经能够按 Conversation 冻结，但 PlanningBrief 和规划图仍只消费景点、餐饮、习惯等旧字符串字段，导致交通、同行、饮食硬约束、无障碍等事实虽然被保存，却不能稳定影响本次方案。需要建立可解释、可排除且随 Run 冻结的记忆投影，让卡片展示与实际规划使用同一份约束。

## What Changes

- 将 PlanningBrief 改为基础行程字段、动态本次约束和长期记忆投影，并保留旧字段的兼容读取。
- 使用严格结构化模型从 Conversation 冻结事实中选择与当前行程相关的 active facts；当前会话和用户手动排除始终优先。
- 扩展 PlanningBrief API、实时事件和卡片，展示本次明确需求、自动带入记忆、排除项及匹配失败重试。
- 在提交时冻结有效约束和覆盖状态，并让路线、景点、餐饮、评审及提示节点按类别消费。
- 统一 `/api/runs` 与 `/api/plan/stream` 兼容入口的事实冻结和约束投影语义，不恢复独立规划页面。
- **BREAKING**：PlanningBrief 的偏好权威表示从三个固定字符串迁移为 `trip_constraints`；旧字段仅保留一个发布周期的输入兼容。

## Capabilities

### New Capabilities

- `memory-aware-planning-brief`: 定义 PlanningBrief 动态约束、记忆相关性投影、用户排除、失败降级和卡片交互。
- `structured-planning-constraints`: 定义不可变 Run 约束快照、规划节点消费、覆盖说明及兼容规划入口行为。

### Modified Capabilities

无。

## Impact

- 数据库：`planning_briefs` 增加记忆投影和匹配状态字段。
- 后端：Chat 结构化输出、PlanningBrief repository/API、Run 创建、规划状态与节点 Prompt、兼容 SSE 入口。
- 前端：方案卡、PlanningBrief API 与状态投影。
- 运行依赖：相关性判断默认复用现有 LLM provider，可用 `PLANNING_MEMORY_MATCH_MODEL` 覆盖。
