## ADDED Requirements

### Requirement: PlanningBrief 使用动态旅行约束
系统 SHALL 将目的地、日期、天数和本次预算与动态旅行约束分开保存，并 SHALL 兼容读取旧偏好字段。

#### Scenario: 旧偏好迁移
- **WHEN** 系统读取包含旧景点、餐饮或习惯字符串的活动 brief
- **THEN** 系统将其无损投影为来源为当前会话的动态约束

### Requirement: 相关长期事实自动投影
系统 SHALL 只从 Conversation 冻结快照中的 active facts 选择与当前行程相关的事实，并 SHALL 校验模型返回的每个 fact ID。

#### Scenario: 语义作用域匹配
- **WHEN** 冻结事实限定日本且当前目的地为东京
- **THEN** 相关性模型可以选择该事实且服务端只在 ID 属于当前冻结快照时应用

#### Scenario: 候选事实存在
- **WHEN** 用户拥有尚未批准的 candidate fact
- **THEN** 该事实不出现在匹配输入、卡片投影或有效约束中

### Requirement: 当前行程需求覆盖长期记忆
系统 SHALL 让当前会话显式约束和用户本次排除优先于模型选择的长期事实，且 SHALL NOT 因本次排除修改长期事实或 revision。

#### Scenario: 本次不采用长期偏好
- **WHEN** 用户在卡片中排除一条自动带入事实
- **THEN** 该事实不进入本次有效约束，但新会话仍可读取它

### Requirement: 匹配并发和失败安全
系统 SHALL 在事务外调用相关性模型并通过上下文 fingerprint 阻止过期结果覆盖新编辑。

#### Scenario: 匹配期间 brief 被修改
- **WHEN** 较旧匹配结果返回时 brief 上下文已经变化
- **THEN** 系统丢弃旧结果且不覆盖最新投影

#### Scenario: 首次匹配失败
- **WHEN** 当前 brief 没有历史成功投影且相关性模型失败
- **THEN** 系统保留显式需求、记录净化错误并允许用户重试或继续规划

### Requirement: 卡片解释记忆来源
系统 SHALL 分组展示本次明确需求、自动带入事实和本次排除事实，并提供排除、恢复及重新匹配操作。

#### Scenario: 用户查看自动填充
- **WHEN** 一个长期事实被应用于当前 brief
- **THEN** 卡片显示事实内容、类别、作用域和“来自长期记忆”标识

#### Scenario: 用户查看负向景点记忆
- **WHEN** 自动带入事实的 polarity 为 `avoid` 且内容为“老门东”
- **THEN** 卡片明确显示“本次避开”和“不纳入候选行程”，排除该规则的操作显示为“本次允许安排”

#### Scenario: 用户查看本次明确约束
- **WHEN** 当前对话形成 `avoid` 或 `require` 动态约束
- **THEN** 本次明确需求区域同时展示类别与极性，不得只显示可能产生反向理解的事实正文

### Requirement: 前端资源版本与方案投影保持一致
系统 SHALL 使方案卡脚本在服务端投影结构升级后重新验证，并 SHALL NOT 因浏览器复用旧前端资源而丢弃新的 PlanningBrief 字段。

#### Scenario: 部署新版方案卡后重新访问
- **WHEN** 用户在已有浏览器会话中重新加载应用
- **THEN** 浏览器加载与当前服务端匹配的卡片脚本，并展示持久化的动态约束和长期记忆投影
