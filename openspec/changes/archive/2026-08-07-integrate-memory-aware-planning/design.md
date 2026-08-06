## Context

Conversation 已冻结 `memory_facts` 快照，Planning Run 也会携带该快照，但 PlanningBrief 仍用固定字符串，规划图只把事实格式化为 `profile_hint` 后交给模型自行合并。现状缺少相关性选择、来源追踪、本次排除、硬约束覆盖说明和跨入口一致性。

## Goals / Non-Goals

**Goals:**

- 使用同一份结构化有效约束驱动卡片、Run snapshot 和规划节点。
- 保证当前会话显式需求、手动编辑和本次排除高于长期记忆。
- 对模型选择的 fact ID 做所有权、状态、快照和并发校验。
- 在不新增外部旅游数据源的前提下诚实表达约束覆盖范围。

**Non-Goals:**

- 不新增酒店、城际交通或无障碍设施数据源。
- 不让相关性模型写入长期记忆。
- 不恢复独立规划页面，也不改变 Conversation 冻结 revision 的生命周期。

## Decisions

### 1. PlanningBrief 分离显式约束与记忆投影

`data_json` 保存基础行程、`trip_constraints` 和 `excluded_memory_fact_ids`；新增列保存模型投影及状态。API 由服务端将投影事实水合为 `memory_context`，并生成 `effective_constraints`。这样用户编辑不会把长期事实复制成会话事实，排除也不会改变画像 revision。

### 2. 相关性判断使用严格结构化模型

模型接收冻结 active facts 和当前 brief，只能针对已有 fact ID 返回 `apply/conflict/irrelevant`、应用级别和枚举原因。服务端拒绝未知、重复、候选或跨用户 ID。相比字面作用域匹配，这能覆盖“日本→东京”等语义关系；代价是增加一次模型调用和失败路径。

### 3. 投影通过 fingerprint 乐观提交

brief 数据先短事务保存，模型调用在事务外执行，结果仅在上下文 fingerprint 未变化时写回。并发更新导致旧结果被丢弃并重新计算，避免长事务和旧投影覆盖新需求。首次失败使用空投影，已有成功结果则保留，并提供显式重试。

### 4. 有效约束是规划权威输入

提交时冻结显式约束、被应用事实、revision、coverage 和兼容字段。规划状态直接消费 `effective_constraints`；旧 `profile_hint` 只由有效约束生成，不再包含未选择的全部画像。当前显式约束优先，用户排除的 fact 不得重新进入 Run。

### 5. 按现有数据能力声明覆盖

景点、餐饮、预算、节奏、作息和同行约束进入对应检索、生成和评审 Prompt。饮食与无障碍为 hard，但没有可靠数据验证时标为 `unverified`。住宿、目的地经历等只作为 advisory/context，不声称已完成酒店或预订级规划。

### 6. 兼容入口复用同一快照构造器

Conversation Run 使用会话冻结快照；无 Conversation 的兼容新规划冻结当前 active facts；修改行程优先继承父 Run 的约束快照，只有旧行程无来源 Run 时才回退当前画像。独立规划 UI 保持隐藏。

## Risks / Trade-offs

- **[相关性模型波动或失败]** → 温度设为 0、严格 ID 校验、保存 fingerprint；失败不丢显式需求并允许重试。
- **[旧 brief 数据形状]** → 读取和提交时将旧三个偏好字段惰性转换为会话约束，`budget` 映射为 `trip_budget`。
- **[约束被提示词接受但数据不可验证]** → 最终 `constraint_coverage` 区分 `applied/advisory/unverified`，禁止虚假承诺。
- **[快照与当前画像不同]** → Conversation 始终使用冻结事实；这是会话一致性的既定语义。
- **[无构建前端复用旧脚本]** → 所有本地资源使用统一发布版本参数，HTML 禁止缓存且静态资源每次重新验证，避免新 SSE 字段被旧 `ChatState` 丢弃。

## Migration Plan

1. 幂等增加 PlanningBrief 投影列并上线兼容解码。
2. 上线投影服务、API 和 Run snapshot，再切换规划节点消费。
3. 切换前端动态卡片，旧输入字段保留一个发布周期。
4. 回滚时忽略新增列并继续读取旧字段；已有原始 brief、facts 和 Run snapshot 均保留。

## Open Questions

无。
