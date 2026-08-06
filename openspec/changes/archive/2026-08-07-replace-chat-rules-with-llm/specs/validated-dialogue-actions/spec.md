## ADDED Requirements

### Requirement: 语言理解与业务执行分离
系统 SHALL 由确定性 DialogueActionExecutor 消费已经校验的 DialogueDecision，并依据结构化 intent、结构化字段和权威资源状态执行动作。执行器 MUST NOT 重新分析原始消息文本以决定 intent、字段或动作。

#### Scenario: 更新可编辑 PlanningBrief
- **WHEN** 校验后的 decision 为 `create_plan` 或 `update_brief` 且包含有效 `brief_patch`
- **THEN** 执行器将增量合并到当前活动 PlanningBrief
- **THEN** 服务端重新计算 readiness 并发布权威 PlanningBrief 事件

#### Scenario: 澄清不产生业务副作用
- **WHEN** decision 包含 clarification 或 intent 为 `unclear`
- **THEN** 执行器只持久化并发布用户可见追问
- **THEN** 执行器不提交 brief、不创建 Revision 且不控制 Run

### Requirement: 消息提交不得预先进行文本路由
`ChatService.submit_message` SHALL 保存用户消息并创建 Chat Run，将显式资源引用作为上下文传递给 Dialogue Agent。该入口 MUST NOT 根据原始文本关键词预绑定 Run、判断控制意图，或因存在 `related_itinerary_id` 直接创建 Revision。

#### Scenario: 已绑定行程上的普通咨询
- **WHEN** 消息带有 `related_itinerary_id` 但 Dialogue Agent 将内容识别为旅行咨询
- **THEN** 系统返回普通回答而不创建 Revision

#### Scenario: 已绑定行程上的修改要求
- **WHEN** 消息带有用户拥有的 `related_itinerary_id` 且 Dialogue Agent 返回 `modify_itinerary`
- **THEN** 执行器使用该明确目标创建独立 Revision Run

### Requirement: 资源引用必须权威校验
执行器 SHALL 验证 decision 中的 Run 和 itinerary 引用存在、属于当前用户且满足目标动作所需状态；模型未获得的、虚构的或越权的资源 ID MUST 被拒绝。

#### Scenario: 模型返回虚构 itinerary
- **WHEN** `modify_itinerary` decision 引用的 itinerary 不存在于提供给模型的上下文或不属于当前用户
- **THEN** 系统拒绝创建 Revision
- **THEN** 系统返回净化后的目标无效错误或澄清

#### Scenario: 多个候选目标
- **WHEN** decision 请求控制或修改资源但没有唯一合法目标
- **THEN** 系统要求用户选择目标
- **THEN** 系统不得自行选择其中一项执行

### Requirement: 正式规划需要结构化明确确认
系统 SHALL 只接受 ready brief 上的明确原子提交操作，或校验后 decision 中的 `confirm_plan`，并 SHALL 在活动 PlanningBrief 为 `ready`、确认尚未消费且幂等校验通过时提交正式规划。用户可见回复中的声明 MUST NOT 代替明确确认。

#### Scenario: 点击确认 ready brief
- **WHEN** 用户在 ready PlanningBrief 上点击“确认，开始规划”
- **THEN** 系统通过现有原子提交操作冻结快照并创建且仅创建一个正式 PlanningRun
- **THEN** 系统不对该按钮命令执行自然语言识别

#### Scenario: 确认 ready brief
- **WHEN** 用户明确确认且 Dialogue Agent 返回 `confirm_plan`，当前 brief 为 `ready`
- **THEN** 系统冻结 PlanningBrief 快照并创建且仅创建一个正式 PlanningRun

#### Scenario: 信息未完整时请求开始
- **WHEN** Dialogue Agent 返回 `confirm_plan` 但当前 brief 仍缺少必填字段
- **THEN** 系统不创建正式 PlanningRun
- **THEN** 系统返回当前最小缺失信息的澄清

#### Scenario: 重复确认
- **WHEN** 同一个已提交 brief 的确认被重复处理
- **THEN** 系统返回已存在的 submitted Run
- **THEN** 系统不创建第二个正式 PlanningRun

### Requirement: 确定性字段校验不得演变为语言识别
执行器 SHALL 校验日期范围、根据已识别的起止日期计算天数、验证允许字段、检查状态转换和执行幂等约束；这些校验 MUST NOT 通过匹配原始文本来补写目的地、偏好、intent 或动作。

#### Scenario: 日期范围无效
- **WHEN** decision 的结束日期早于开始日期
- **THEN** 系统拒绝合并该日期范围并请求用户澄清
- **THEN** 系统不从原始文本尝试另一套日期解释

#### Scenario: 天数与日期不一致
- **WHEN** decision 给出的天数与有效起止日期不一致
- **THEN** 系统以权威日期范围重新计算规范化天数
- **THEN** 系统保留模型识别的其他合法字段

### Requirement: Run 控制遵守状态机与确认边界
执行器 SHALL 仅执行 schema 允许的 `run_action`，并 SHALL 在操作前校验 Run 所有权、当前状态、唯一目标和所需确认；不合法动作 MUST 被拒绝且不得改变 Run。

#### Scenario: 停止唯一活动任务
- **WHEN** decision 请求停止用户拥有且当前可取消的唯一目标 Run，并已满足确认要求
- **THEN** 执行器通过现有 RunManager 取消该 Run

#### Scenario: 对已完成任务执行停止
- **WHEN** decision 请求停止一个已经 succeeded 的 Run
- **THEN** 执行器拒绝状态转换并返回该任务已经完成的用户可见说明
