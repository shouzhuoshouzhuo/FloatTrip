# travel-memory-facts Specification

## Purpose
Define scoped, traceable travel-memory facts with activation rules, correction, forgetting, auditing, and immutable planning snapshots.

## Requirements

### Requirement: Travel memory facts are scoped and traceable
系统 SHALL 以带分类、极性、作用域、来源、证据和状态的事实保存长期旅游记忆，并 SHALL 支持 global、destination、companion 和 destination_companion 作用域。

#### Scenario: Destination-scoped preference is extracted
- **WHEN** 用户明确表示“去日本时偏爱温泉”
- **THEN** 系统保存 destination 作用域的 attraction preference，而不是无条件全局偏好

### Requirement: Explicit, inferred and sensitive memories have different activation rules
系统 SHALL 自动激活用户明确表达的普通旅行事实，MUST 把推断事实以及过敏、医疗饮食和无障碍事实保存为待确认候选，并 MUST 丢弃禁止保存的个人信息。

#### Scenario: Explicit ordinary preference
- **WHEN** 用户明确表示通常喜欢博物馆
- **THEN** 系统创建 active 全局事实并记录证据消息

#### Scenario: Protected accessibility fact
- **WHEN** 用户明确描述行动能力限制
- **THEN** 系统创建 candidate 且在用户批准前不得注入新会话

#### Scenario: Prohibited personal information
- **WHEN** 对话包含证件号、联系方式、精确住址或支付信息
- **THEN** 系统不得把该内容保存为 memory fact

### Requirement: Corrections and forgetting preserve audit history
系统 SHALL 通过 supersede 或软删除处理明确纠正和遗忘，不得把相互矛盾的 active 事实简单并列追加。

#### Scenario: User corrects a preference
- **WHEN** 用户明确用新偏好替代已有 active 事实
- **THEN** 旧事实变为 superseded，新事实变为 active，用户 memory revision 递增

#### Scenario: User asks to forget
- **WHEN** 用户明确要求忘记匹配事实
- **THEN** 匹配事实立即软删除且不再进入任何新快照

### Requirement: Planning uses an immutable memory snapshot
从 Conversation 创建的正式规划 SHALL 使用该 Conversation 的冻结记忆；独立规划 SHALL 在 Run 创建时冻结当时最新事实。

#### Scenario: Profile changes after plan submission
- **WHEN** Conversation 已提交规划且随后画像发生变化
- **THEN** 已提交规划继续使用其 request snapshot 中的原记忆版本
