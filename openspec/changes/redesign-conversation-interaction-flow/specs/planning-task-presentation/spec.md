## ADDED Requirements

### Requirement: Run 状态具有用户可理解的表达
页面 SHALL 为 `queued`、`running`、`waiting_user`、`succeeded`、`failed` 和 `cancelled` 显示文字状态、含义和适用动作，并 SHALL NOT 仅依赖颜色或动画表达状态。

#### Scenario: 任务排队
- **WHEN** Run 状态为 `queued`
- **THEN** 页面说明任务已保存且会自动开始，并提供停止任务操作

#### Scenario: 任务被取消
- **WHEN** Run 状态为 `cancelled`
- **THEN** 页面使用中性终态表达任务已停止，并在允许时提供重新开始操作

### Requirement: 进度映射为产品阶段
正式规划任务 SHALL 将内部进度事件映射到少量稳定、用户可理解的产品阶段，并 SHALL 默认隐藏内部节点名、模型推理和技术日志。

#### Scenario: Reviewer 反复优化
- **WHEN** `planner` 与 `reviewer` 在多轮执行中交替产生事件
- **THEN** 页面保持在“编排行程与优化路线”阶段，而不是向用户展示内部循环

#### Scenario: 任务进入餐饮与贴士节点
- **WHEN** 任务开始处理餐饮推荐、景点贴士或最终收敛
- **THEN** 页面将当前阶段显示为“完善旅行细节”

### Requirement: 不展示无依据的确定性进度
页面 SHALL 使用离散阶段与当前活动描述表达进度，除非后端提供可验证的完成比例，否则 MUST NOT 展示百分比或确定的剩余时间。

#### Scenario: 节点耗时未知
- **WHEN** 正式规划正在执行且没有可靠剩余时间数据
- **THEN** 页面显示当前阶段和“可以离开页面继续聊天”等保障信息，不显示虚假百分比

### Requirement: 等待用户状态成为当前主操作
`waiting_user` 任务 SHALL 显著显示安全问题、输入控件和继续操作，并 SHALL 在刷新后恢复相同 interaction。

#### Scenario: 任务请求补充信息
- **WHEN** Run 进入 `waiting_user`
- **THEN** 页面把对应任务标记为“需要你的回复”，显示问题并将主要操作设置为提交该 interaction 的回答

#### Scenario: 提交有效回答
- **WHEN** 用户对当前 interaction 提交有效值
- **THEN** 页面防止重复提交、恢复同一个 Run，并将状态更新为继续规划

### Requirement: 完成态提供成果预览
成功任务 SHALL 在时间线中展示来自权威行程数据的简短成果摘要，并 SHALL 提供打开完整行程的主要操作。

#### Scenario: 正式规划成功
- **WHEN** Run 状态为 `succeeded` 且存在 `result_itinerary_id`
- **THEN** 页面显示目的地、日期或天数等可用摘要，并提供“打开完整行程”

#### Scenario: 继续修改完成行程
- **WHEN** 用户从成功卡选择继续修改
- **THEN** 后续修改输入明确绑定到该 `result_itinerary_id`

### Requirement: 失败态支持恢复
失败任务 SHALL 显示经过净化的用户错误、请求是否保留及可用恢复动作。

#### Scenario: 可重试失败
- **WHEN** Run 以可重试错误失败
- **THEN** 页面说明原需求仍被保留并提供创建新重试 Run 的操作

#### Scenario: 重试已创建
- **WHEN** 用户重试失败任务
- **THEN** 原失败卡保持终态，新尝试作为关联但独立的任务显示

### Requirement: 对话在后台任务运行时保持可用
页面 SHALL 在非 Chat Run 排队、运行或等待输入期间保持普通消息输入可用，并 SHALL 明确区分普通消息与针对某个任务的回答。

#### Scenario: 运行中继续聊天
- **WHEN** 一个正式规划 Run 正在运行
- **THEN** 用户仍能发送普通聊天消息且该消息不会被当作 Run resume

#### Scenario: 回复指定任务
- **WHEN** 用户从活动任务摘要进入回复模式
- **THEN** 输入区显示目标任务上下文并将提交绑定到对应 interaction

### Requirement: 状态变化可被辅助技术感知
任务卡 SHALL 使用语义化标题和操作标签；重要异步状态变化 SHALL 通过适当的 live region 播报，同时避免逐 token 或装饰动画造成重复播报。

#### Scenario: 任务需要用户回复
- **WHEN** Run 从 `running` 变为 `waiting_user`
- **THEN** 辅助技术收到一次包含任务名称和所需动作的状态通知

#### Scenario: 键盘执行主要操作
- **WHEN** 键盘用户聚焦任务卡
- **THEN** 用户能够按逻辑顺序访问问题输入、继续、停止、重试或打开结果等可用操作
