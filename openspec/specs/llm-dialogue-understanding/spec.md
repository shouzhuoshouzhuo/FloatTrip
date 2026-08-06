# llm-dialogue-understanding Specification

## Purpose
Define LLM-only natural-language understanding with bounded context, unified intent classification, strict structured output, and side-effect-free failure.

## Requirements

### Requirement: LLM 是唯一自然语言理解来源
系统 SHALL 将每条普通 Conversation Message 交给结构化 LLM Dialogue Agent，以识别意图、旅行字段、目标引用、澄清需求和用户可见回复。Chat 理解路径 MUST NOT 使用关键词列表、正则表达式或固定句式对原始文本进行意图分类、字段抽取、动作识别或 fallback。

#### Scenario: 省略介词的正式规划表达
- **WHEN** 用户在 2026-07-23 输入“明天南京3日游”
- **THEN** Dialogue Agent 返回创建规划意图，并识别目的地为南京、开始日期为 2026-07-24、结束日期为 2026-07-26、天数为 3
- **THEN** 系统不得追问已经明确给出的目的地

#### Scenario: 不允许规则降级
- **WHEN** LLM 调用或结构化解析最终失败
- **THEN** 系统返回可重试理解失败状态
- **THEN** 系统不得调用关键词、正则或固定句式解析原始消息

### Requirement: 使用完整且有界的对话上下文
Dialogue Agent SHALL 接收当前日期与时区、当前消息、最近的有界消息历史、活动 PlanningBrief、相关 Run 摘要以及显式绑定 itinerary 摘要，并 MUST NOT 接收其他用户资源或完整内部 planner checkpoint。

#### Scenario: 多轮补充规划需求
- **WHEN** 活动 PlanningBrief 已包含南京和三天行程，用户随后输入“别太赶，想多吃当地小吃”
- **THEN** Dialogue Agent 将现有 brief 作为上下文，并只返回节奏与餐饮偏好的增量
- **THEN** 已收集的目的地和日期保持不变

#### Scenario: 用户纠正已识别字段
- **WHEN** 当前 brief 的目的地为南京且用户输入“不是南京，是南宁”
- **THEN** Dialogue Agent 返回更新 brief 的意图并将目的地修正为南宁
- **THEN** 未被纠正的日期和天数不被清除

### Requirement: 统一识别对话与业务意图
Dialogue Agent SHALL 使用受限枚举区分旅行咨询、普通聊天、创建规划、更新 brief、确认规划、修改 itinerary、控制 Run 和不确定输入，并 SHALL 为每个结果返回与结构化事实一致的用户可见回复。

#### Scenario: 咨询不创建规划
- **WHEN** 用户输入“十月南京适合玩吗”
- **THEN** Dialogue Agent 将消息识别为旅行咨询并直接回答
- **THEN** 系统不创建 PlanningBrief 或正式 PlanningRun

#### Scenario: 自然承接形成正式规划
- **WHEN** 对话正在比较南京与苏州，用户随后输入“那就南京吧，三天，不要太赶”
- **THEN** Dialogue Agent 结合历史将消息识别为创建或补充规划
- **THEN** 结构化结果包含南京、三天和轻松节奏偏好

#### Scenario: 不确定目标时主动澄清
- **WHEN** 用户要求“修改第三天”且上下文中存在多份可修改 itinerary，用户也未显式绑定目标
- **THEN** Dialogue Agent 返回不执行修改的澄清结果
- **THEN** 回复要求用户选择具体行程

### Requirement: 严格结构化输出
Dialogue Agent 的结果 MUST 通过 Pydantic schema 校验，未知 intent、未知动作、未知字段或类型不匹配 MUST 被拒绝，且系统 SHALL NOT 从自由文本回复反向推断业务动作。

#### Scenario: 模型返回未知动作
- **WHEN** 模型返回 schema 未定义的 `run_action`
- **THEN** 该结果不进入业务执行器
- **THEN** 系统触发一次结构化修复

#### Scenario: 回复与动作冲突
- **WHEN** 模型回复文本声称“已经开始规划”但结构化 intent 不是 `confirm_plan`
- **THEN** 系统不得创建正式 PlanningRun
- **THEN** 后续业务行为只依据校验后的结构化字段

### Requirement: 理解失败明确且无副作用
系统 SHALL 在首次结构化结果失败后最多发起一次修复；第二次失败 SHALL 使 Chat Run 进入公开可重试的失败状态，保留用户消息，并且不得更新 PlanningBrief、创建 Revision 或控制其他 Run。

#### Scenario: 两次结构化结果均无效
- **WHEN** 初次模型输出和一次修复输出都无法通过 schema
- **THEN** 用户看到“这条消息暂时没有理解成功，请重试”或等价的净化错误
- **THEN** 原始用户消息保持可见且可以重新发起关联重试
- **THEN** 所有规划与任务资源保持不变
