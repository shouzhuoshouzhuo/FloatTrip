## ADDED Requirements

### Requirement: 渐进式收集规划需求
系统 SHALL 在对话中复述已理解的旅行信息，并 SHALL 优先询问当前阻止正式规划的最小信息集合。

#### Scenario: 缺少具体日期
- **WHEN** 用户已提供目的地和天数但没有有效开始与结束日期
- **THEN** 系统显示已理解的目的地和天数，并聚焦询问日期范围

#### Scenario: 必填信息完整
- **WHEN** 目的地及有效日期范围均已收集
- **THEN** 系统停止必填追问并展示可确认的需求摘要

### Requirement: 问题使用匹配的输入控件
等待用户输入的界面 SHALL 根据安全的 `input_schema` 或明确的问题类型选择日期范围、单选、多选或文本输入；无法识别时 SHALL 降级为文本输入。

#### Scenario: 请求日期范围
- **WHEN** 待补充内容是开始与结束日期
- **THEN** 页面提供日期范围输入并在提交前检查结束日期不早于开始日期

#### Scenario: 未知输入结构
- **WHEN** `input_schema` 不对应受支持控件
- **THEN** 页面提供带问题说明的文本输入且仍可恢复同一交互

### Requirement: 可选项允许采用默认值
系统 SHALL 区分必填信息与可选偏好，并 SHALL 允许用户对可选项明确采用推荐默认值。

#### Scenario: 未提供预算或饮食偏好
- **WHEN** 必填信息已完整而可选偏好缺失
- **THEN** 需求摘要标明将采用的默认处理，且不阻止用户开始正式规划

### Requirement: 可编辑的确认摘要
系统 SHALL 在创建正式 PlanningRun 前展示可编辑摘要，覆盖目的地、日期、天数以及已收集的预算、餐饮和出行习惯偏好。

#### Scenario: 用户调整已识别信息
- **WHEN** 用户在确认前修改需求摘要并保存
- **THEN** 系统更新同一个 PlanningBrief、重新计算 readiness 且不创建 Run

#### Scenario: 用户明确确认
- **WHEN** `ready` 的 PlanningBrief 上用户选择“开始规划”
- **THEN** 系统提交不可变快照并创建且仅创建一个正式 PlanningRun

### Requirement: 运行中变更必须显式处理
系统 SHALL NOT 暗中改变正在运行的正式规划请求，并 SHALL 在用户提出新约束时提供清晰的后续处理选择。

#### Scenario: 运行中新增约束
- **WHEN** 用户对正在执行的规划说“不要安排丽江”
- **THEN** 页面提供“停止并按新要求重新规划”或“完成后创建修改任务”的明确选择

#### Scenario: 用户继续普通聊天
- **WHEN** 正式规划运行时用户提出与请求变更无关的普通旅行问题
- **THEN** 系统继续普通对话且不修改活动 Run 的请求快照

### Requirement: 放弃需求需要清晰结果
系统 SHALL 使用说明结果的操作文案处理未提交需求的放弃，并 SHALL 避免将其与停止已运行任务混淆。

#### Scenario: 清除未提交需求
- **WHEN** 用户选择清除一个 `collecting` 或 `ready` PlanningBrief
- **THEN** 页面说明该需求摘要将被移除且不会创建规划任务
