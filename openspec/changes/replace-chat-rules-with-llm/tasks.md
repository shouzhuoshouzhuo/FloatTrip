## 1. 结构化对话契约

- [x] 1.1 定义严格的 `DialogueDecision`、`PlanningBriefPatch`、`DialogueTarget` 和 `DialogueClarification` Pydantic schema，禁止未知 intent、动作和字段
- [x] 1.2 编写统一 Dialogue Agent prompt，明确当前日期与时区、多轮上下文、字段纠正、咨询/规划区分、资源引用和禁止虚构执行结果
- [x] 1.3 实现一次结构化 LLM 调用同时生成用户回复与语义动作，并复用受 schema 约束的结构化调用能力
- [x] 1.4 实现最多一次的结构化修复；第二次失败产生净化、可重试且无业务副作用的 Chat Run 错误

## 2. 有界对话上下文

- [x] 2.1 扩展 `ChatService.chat_input`，提供当前日期、`Asia/Shanghai` 时区、当前消息和有界的最近消息历史
- [x] 2.2 将活动 PlanningBrief 和当前对话相关 Run 的公开摘要加入 Agent 上下文，并排除内部 prompt、planner checkpoint 和其他用户资源
- [x] 2.3 加载并校验显式绑定的 `related_run_id` 与 `related_itinerary_id`，只向 Agent 提供用户拥有的目标摘要和版本信息
- [x] 2.4 为上下文大小、消息顺序、当前消息去重和资源隔离增加契约测试

## 3. Dialogue Action 执行器

- [x] 3.1 新建不读取原始消息文本的 `DialogueActionExecutor`，按校验后的 intent 分派回复、brief、确认、revision、run control 和 clarification
- [x] 3.2 实现 `create_plan` 与 `update_brief` 的 PlanningBrief 增量合并、日期范围校验、天数规范化、readiness 重算和公共事件发布
- [x] 3.3 接入 ready brief 的 `confirm_plan` 文本确认路径，并与现有按钮原子提交共用幂等语义，证明重复确认不会创建第二个 Run
- [x] 3.4 实现 `modify_itinerary` 的所有权、唯一目标和可修改 checkpoint 校验，再创建携带不可变请求快照的 Revision Run
- [x] 3.5 实现受限 `run_control` 动作的所有权、状态机、目标歧义和确认校验，并复用 `RunManager` 执行合法操作
- [x] 3.6 确保 clarification、无效目标、无效日期和不合法状态只产生用户可见说明，不改变 PlanningBrief、Itinerary 或 Run

## 4. 单一 LLM Chat Graph

- [x] 4.1 用单一 `dialogue_agent` 节点替换现有 classify、extract 和模板 respond 分支，并让普通问答也由同一次结构化调用回答
- [x] 4.2 调整 Chat finalizer，使其通过 DialogueActionExecutor 持久化自然回复与业务结果，并保持现有 Conversation Message 和 SSE 公共事件协议
- [x] 4.3 修改 `ChatService.submit_message`，删除 `control_text` 关键词预路由、隐式候选 Run 绑定和 `related_itinerary_id` 直接创建 Revision 的快捷路径
- [x] 4.4 删除 `_FORMAL_WORDS`、`_EXPLORATION_WORDS`、`_REVISION_WORDS`、`_CONTROL_WORDS`、所有 Chat 文本正则及固定句式识别函数
- [x] 4.5 增加架构边界测试，禁止 Chat 理解和执行模块重新引入基于原始消息的正则、关键词枚举或规则 fallback

## 5. 失败、重试与用户体验

- [x] 5.1 为模型超时、provider 错误、无效结构和修复失败定义净化的公开错误类型，确保不泄露 prompt、原始响应或内部异常
- [x] 5.2 让对话时间线显示 Chat 理解失败及“重试这条消息”操作，并关联创建新的重试 Chat Run
- [x] 5.3 验证失败期间保留原始用户消息、刷新后仍可重试，并且不会显示虚假的“目的地缺失”或成功文案
- [x] 5.4 验证模型返回的自由文本声明不能替代结构化 `confirm_plan`、`modify_itinerary` 或 `run_control` 动作

## 6. 行为测试与质量门槛

- [x] 6.1 使用假结构化 LLM 覆盖全部 intent、schema 拒绝、一次修复、无副作用失败和回复持久化单元测试
- [x] 6.2 增加 PlanningBrief、确认幂等、Revision、Run 控制、越权资源和多目标歧义的 runtime/API 集成测试
- [x] 6.3 建立中文自然语言评测集，覆盖“明天南京3日游”、省略介词、口语日期、多轮补充、纠正、咨询/规划区分、修改和控制
- [x] 6.4 删除依赖旧分类器、正则抽取器和固定模板回复的测试，并确认评测断言结构化语义而非逐字模型文案
- [x] 6.5 运行全部 Python 与前端测试、OpenSpec 校验和静态边界检查，修复本变更引入的回归
- [x] 6.6 启动本地应用，通过真实浏览器验证普通咨询、南京三日游、补充偏好、纠正目的地、确认规划、行程修改、任务控制、失败重试和刷新恢复
- [x] 6.7 确认代码库不存在 Chat 规则识别 fallback、影子模式或运行时 feature flag 后，直接启用新路径
