## Context

当前 Chat 通过主库消息重建上下文，但查询最多先取最早 200 条再截取 12 条，长对话会停止看到新历史。LangGraph checkpointer 使用 `run_id`，适合执行恢复而非 Conversation 记忆。长期画像是四组无来源字符串，无法表达作用域、纠正、候选和敏感信息治理。

项目同时支持 DeepSeek 和 4K 豆包模型，必须在不增加 tokenizer 依赖的情况下控制输入预算。Messages、PlanningBrief、Run 和 itinerary 已经是各自领域的权威状态，摘要不能替代这些结构化实体。

## Goals / Non-Goals

**Goals:**

- 为每个 Conversation 建立冻结画像、累计摘要和压缩游标。
- 使用真实 System/Human/AI 消息组装 Prompt，并定义明确覆盖优先级。
- 以持久、幂等任务从被压缩或归档的对话提取旅游长期事实。
- 让用户管理生效事实和待确认候选，并保护敏感信息。
- 让 Conversation 发起的规划复用相同冻结画像。

**Non-Goals:**

- 不改变 `run_id` checkpoint 隔离。
- 不增加会话 TTL、自动空闲归档、Run event/checkpoint 清理或多节点租约。
- 不把 PlanningBrief、Run 或 itinerary 降级为自然语言摘要。

## Decisions

### 1. 应用数据库承载 Conversation 记忆

新增 `conversation_memory_states`，在首条消息事务中复制当时 active facts 和用户 revision。Chat checkpoint 仍以 `run_id` 隔离，避免重试、interrupt 和规划状态相互污染。冻结事实后，本会话仅通过当前消息、最近历史和摘要表达纠正，新长期事实只影响新会话。

### 2. Prompt 使用分层真实消息

Prompt 顺序固定为静态系统规则、动态日期、隐藏长期快照、隐藏摘要、权威应用状态、最近真实角色消息和当前消息。隐藏数据使用命名 HumanMessage 并由 system 明确标为 data-only，避免把用户来源文本提升为系统指令。覆盖优先级为当前消息、最近历史、摘要、冻结画像。

### 3. 结构化累计摘要按预算滚动

默认输入预算 3000 token，2600 触发，摘要目标 600 token，保留最近 6 个完整轮次。估算器按 CJK 字符 1 token、其他字符约 4 字符/token，并加入消息开销。只在 AssistantMessage 边界压缩；先创建提取任务，再原子替换摘要与游标。失败时保留旧摘要并使用预算内最新历史。

### 4. 事实存储采用事件式替代而非数组覆盖

`memory_facts` 保存分类、极性、作用域、来源、证据、敏感级别和替代关系。编辑和纠正创建新事实并 supersede 旧事实，删除为软删除。普通明确事实自动 active；推断、过敏/无障碍等保护事实进入 candidate；证件、联系方式、精确地址和支付信息不落库。

### 5. 提取任务最终一致且可重放

压缩前与归档时写入唯一范围任务。单节点后台 worker 最多重试 5 次；消息原文不删除，因此进程重启后可以重新领取 `pending` 任务，并把遗留 `running` 重置为 `pending`。归档立即只读，最终归并状态单独暴露，允许失败重试。

### 6. 旧画像一次迁移，新事实库立即成为权威源

旧三类偏好迁为全局 active facts；历史目的地迁为 legacy candidate，避免把“规划过”误当“去过”。迁移使用固定 fingerprint 幂等执行，旧表保留但不再读写。规划层通过事实投影生成 prompt 文本，不保留双写。

### 7. 画像页使用旅行档案视觉

界面沿用现有暖色旅行手账语言，以“已记住 / 待确认 / 作用域”卡片呈现事实；提供批准、编辑、忽略和遗忘操作。归档对话显示只读徽标与整理状态，不引入新的导航体系。

### 8. 主动压缩复用自动压缩语义

Chat 页提供“主动压缩”入口，但不引入另一套摘要格式或删除策略。服务端复用累计摘要、AssistantMessage 边界、最近轮次保留和 `pre_summary` 提取任务；短会话幂等返回无需压缩，归档会话拒绝操作，摘要失败继续保留旧摘要和全部原始消息。

## Risks / Trade-offs

- **[摘要模型失败]** → 原始消息不删除，保留旧摘要并退化为预算内最近消息。
- **[异步归档导致新会话暂时读不到新事实]** → 明确展示整理状态，失败可重试；这是选定的最终一致语义。
- **[LLM 错误提取事实]** → 只自动应用明确普通事实；证据范围、所有权、ID 和枚举由服务端校验。
- **[SQLite 后台任务竞争]** → 使用短 `BEGIN IMMEDIATE` 领取和原子状态转换，单节点 worker 串行处理。
- **[Prompt 注入经记忆持久化]** → 记忆作为 data-only HumanMessage，禁止存储 instruction 类内容和 PII。
- **[Breaking profile API]** → 同一发布中同步更新前端、规划投影和测试，旧表保留用于回滚。

## Migration Plan

1. 添加幂等表/列迁移与旧画像 backfill，不切换读路径。
2. 上线事实仓库、会话快照、摘要和提取 worker，再切换 Chat/Planning 读路径。
3. 切换 Profile/Memory API 与前端，停止旧画像写入。
4. 通过数据库备份和迁移测试验证后发布；回滚时恢复旧代码读取保留的 `user_profiles` 表。

## Open Questions

无。
