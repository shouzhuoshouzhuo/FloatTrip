# conversation-attention Specification

## Purpose
Define persistent, accessible conversation-list indicators for runs needing user input, unread completed itineraries, and visibility-aware acknowledgement.

## Requirements

### Requirement: 会话列表聚合正式规划状态
系统 SHALL 为用户拥有的每个 Conversation 返回正式规划的进行中、待用户处理和完成未读状态，并 MUST NOT 将普通 Chat Run 计入规划提醒。

#### Scenario: 其他会话正在后台规划
- **WHEN** Conversation 存在状态为 `queued` 或 `running` 的 `travel_plan/revision` Run
- **THEN** 会话列表将其标记为规划中

#### Scenario: 只有普通聊天正在执行
- **WHEN** Conversation 只有状态为 `running` 的 Chat Run
- **THEN** 会话列表不显示规划中状态

### Requirement: 待处理状态保持可见
系统 SHALL 在存在 `waiting_user` 正式 Run 或 ready PlanningBrief 时显示需要用户处理的提醒，并 SHALL 在用户仅打开会话后继续保留，直到对应交互或确认完成。

#### Scenario: 方案卡等待确认
- **WHEN** Conversation 存在 ready PlanningBrief
- **THEN** 侧栏显示“待确认”提醒

#### Scenario: 规划运行等待补充
- **WHEN** 正式 Run 进入 `waiting_user`
- **THEN** 侧栏显示“待你回复”提醒且优先于其他状态

### Requirement: 完成未读持久化
系统 SHALL 根据成功正式 Run 的终态时间和 Conversation 的 `last_viewed_at` 判断完成未读，并 SHALL 通过有所有权校验的幂等接口标记已查看。

#### Scenario: 后台规划完成但尚未打开
- **WHEN** 正式 Run 在 `last_viewed_at` 之后成功且用户尚未查看该 Conversation
- **THEN** 侧栏显示“新行程”未读提醒

#### Scenario: 用户打开完成会话
- **WHEN** 用户在可见页面加载完成该 Conversation
- **THEN** 系统更新 `last_viewed_at` 且完成未读提醒消失

#### Scenario: 跨用户标记查看
- **WHEN** 用户尝试标记其他用户的 Conversation 已查看
- **THEN** 系统返回 404 且不修改查看游标

### Requirement: 页面可见性保护未读
前端 SHALL 只在页面可见时标记当前 Conversation 已查看，并 SHALL 在页面重新可见时立即刷新列表和当前查看状态。

#### Scenario: 后台标签页收到完成事件
- **WHEN** 当前 Conversation 的正式 Run 在页面隐藏时成功
- **THEN** 前端不清除完成未读状态

### Requirement: 侧栏状态具有明确视觉和无障碍语义
前端 SHALL 使用加载动画表达规划中，使用文字与形状提醒待处理和完成未读，并 SHALL 为状态提供可读的辅助技术标签。

#### Scenario: 多个状态同时存在
- **WHEN** 一个 Conversation 同时满足多个关注状态
- **THEN** 前端按“待你回复、待确认、规划中、新行程”的顺序展示最高优先级状态

#### Scenario: 减少动态效果
- **WHEN** 用户启用 `prefers-reduced-motion`
- **THEN** 加载图标停止旋转但仍保留可识别的规划中标签
