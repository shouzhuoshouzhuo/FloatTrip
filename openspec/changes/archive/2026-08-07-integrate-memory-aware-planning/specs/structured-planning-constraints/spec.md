## ADDED Requirements

### Requirement: Planning Run 冻结有效约束
系统 SHALL 在提交 PlanningBrief 时将显式约束、应用事实、画像 revision、有效约束和覆盖状态写入不可变 Run snapshot，并保持重复提交幂等。

#### Scenario: 提交已确认 brief
- **WHEN** 用户提交 ready brief
- **THEN** 创建且仅创建一个携带确认时约束快照的 Travel Plan Run

### Requirement: 规划节点按类别消费约束
系统 SHALL 将景点、餐饮、预算、节奏、作息、同行、无障碍和交通约束提供给相关规划节点，而不是把未筛选画像整体作为提示文本。

#### Scenario: 饮食硬约束
- **WHEN** 有效约束要求避开花生
- **THEN** 餐饮检索和推荐收到该要求，无法从数据验证时结果标记为 `unverified`

#### Scenario: 负向景点约束进入规划
- **WHEN** 有效约束包含 polarity 为 `avoid` 的景点“老门东”
- **THEN** 规划节点收到明确的“必须避开：老门东”指令，而不是把“老门东”作为普通景点偏好

#### Scenario: 住宿偏好缺少数据源
- **WHEN** 有效约束包含住宿偏好但系统没有酒店数据源
- **THEN** 系统将其标为 advisory 且不声称已完成酒店推荐或预订

### Requirement: 最终结果说明约束覆盖
系统 SHALL 在 itinerary 中保存每条有效约束的应用阶段和 `applied/advisory/unverified` 状态。

#### Scenario: 查看规划结果来源
- **WHEN** 规划完成并保存 itinerary
- **THEN** 结果可追溯到本次显式约束或冻结 fact ID 及其覆盖状态

### Requirement: 所有规划入口使用一致快照语义
系统 SHALL 让 Conversation Run、独立兼容 Run 和旧修改流程使用同一约束构造器，同时保持独立规划页面隐藏。

#### Scenario: 修改已有行程
- **WHEN** `/api/plan/stream` 修改一个存在来源 Run 的 itinerary
- **THEN** 修改 Run 继承父 Run 的有效约束，并由本次修改意见覆盖

#### Scenario: 旧行程缺少来源快照
- **WHEN** 修改的旧 itinerary 无法定位父 Run 约束
- **THEN** 系统冻结当前 active facts 作为兼容回退并记录来源
