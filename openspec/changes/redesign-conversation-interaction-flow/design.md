## Context

现有前端已经能够加载持久化 Conversation、Message、PlanningBrief 和 Run，并通过 SSE 重放与订阅事件。Run 生命周期、不可变请求快照、等待用户恢复、取消、重试和结果关联均已存在，问题主要位于前端信息架构与状态投影：

- `ChatPage` 先渲染全部消息，再渲染全部 brief，最后渲染全部非 Chat Run，破坏了事件的因果顺序。
- `PlanningBriefCard` 仅突出目的地和日期，编辑范围没有覆盖已收集的预算、餐饮与习惯偏好。
- `RuntimeRunCard` 直接展示单条内部节点标签，缺少稳定产品阶段、成果预览和多任务上下文。
- 导航同时提供旧 `PlanPage` 与旅行对话两套创建规划路径。
- 认证模态框关闭后没有保存并恢复触发认证的目标动作。
- 等待用户统一使用文本框，没有将 `input_schema` 投影为合适控件。

本变更面向旅行者、需要同时处理多个对话或任务的回访用户，以及使用键盘或辅助技术的用户。后端 Run 与事件协议保持为可信状态源。

## Goals / Non-Goals

**Goals:**

- 建立一个按因果与时间排序的统一活动时间线。
- 将 PlanningBrief 变成对话式收集、可编辑确认和正式启动之间的清晰边界。
- 用稳定产品阶段表达运行进度，并覆盖所有 Run 状态和恢复动作。
- 统一新建规划入口并在认证后恢复用户意图。
- 支持后台规划、多任务、刷新恢复、移动端和基本无障碍交互。
- 复用现有运行时 API 与数据模型，保持实现范围聚焦前端。

**Non-Goals:**

- 改变 LangGraph 节点、规划质量、并发调度或 provider 配置。
- 暴露 chain-of-thought、原始 prompt、完整图状态或内部模型输出。
- 引入虚假的百分比、确定剩余时间或尚无数据支撑的队列位置。
- 重做行程详情、地图、手动编辑、历史页或画像页。
- 在本变更中删除后端旧规划兼容 API；前端入口迁移后再评估清理。

## Decisions

### 1. 使用统一 ActivityItem 投影，而不是三段实体列表

`ChatState` 保持 messages、briefs、runs 和 cursors 的规范化实体存储，并新增一个纯派生的活动时间线投影。每个 ActivityItem 包含稳定 `key`、`type`、`entityId`、`conversationId`、排序锚点和可选关联目标。

排序优先级如下：

1. Message 使用 conversation `sequence`。
2. PlanningBrief 使用 `created_at` 作为首次锚点，并在更新时保持该锚点。
3. 非 Chat Run 使用 `created_at`，并关联其 brief、retry 或 itinerary 上下文。
4. 时间相同时使用类型优先级和稳定 ID 作为确定性兜底。

实体状态变化只更新规范化存储，不追加新 ActivityItem。该方式复用现有资源模型，且比把每个 UI 变化持久化成 ConversationEvent 改动更小。

备选方案是新增全局 conversation event sequence。它能提供最严格的跨实体排序，但需要数据库、API 与迁移变更，暂不作为首选；若时间戳不足以通过恢复一致性测试，再升级协议。

### 2. 活动卡固定在时间线，活动摘要只提供定位

完整 brief、run 与结果卡只在时间线存在一次。通过 IntersectionObserver 或等价可测试机制判断活动卡是否离开视口，并在页头或 composer 上方显示一行活动任务摘要。点击摘要滚动并聚焦原卡。

不使用右侧固定任务栏，因为三栏布局会压缩对话阅读宽度，在移动端也会产生第二套信息架构。

### 3. 唯一对话入口与受控旧 PlanPage

应用默认落点、品牌点击和退出登录后均进入旅行对话。顶栏不显示“首页”或“新建规划”；旅行对话的空状态即为创建新规划的入口，已有对话则恢复最近会话。`PlanPage` 暂时保留为不可见的受控兼容实现，仅从行程详情的修改流程进入，直到新对话流覆盖修改顾虑和结果打开的回归测试。

认证请求保存 `{page, action, payload}` 形式的待继续目标。认证成功后只消费一次；关闭模态框则清除该目标。

直接删除 `PlanPage` 被拒绝，因为行程修改仍依赖它，立即移除会扩大本变更风险；但其默认导航入口与产品介绍首页应移除。

### 4. Brief 卡采用摘要优先、按需编辑

默认态使用“这趟旅行，我理解的是”表达，而不是后台式“规划需求单”。摘要分为：

- 核心必填：目的地、开始日期、结束日期和推导天数；
- 已知偏好：预算、餐饮、节奏或习惯；
- 默认处理：未提供但不阻止提交的可选项；
- 缺失项：当前唯一主要问题。

编辑态复用 `PATCH /api/planning-briefs/{id}`，覆盖后端已经接受的字段。保存后由服务端重新计算 readiness。正式提交继续使用原子 `submit` API，前端按钮在请求期间禁用以避免重复创建。

### 5. 从 input_schema 到有限控件注册表

实现安全、有限的控件映射：

- 日期范围问题 → 两个 `date` 输入；
- `enum` → 单选；
- 字符串数组或多选 schema → 复选；
- 普通 string → 文本或 textarea；
- 未识别 schema → 文本降级。

控件只解释允许的展示字段，不执行 schema 中的代码或任意 HTML。客户端进行即时验证，服务端仍是最终验证者。

### 6. 将内部节点映射为四个产品阶段

前端维护稳定映射：

| 产品阶段 | 内部 stage |
|---|---|
| 理解旅行需求 | `intent`, `query_rewrite` |
| 搜集目的地信息 | `attraction_search` |
| 编排行程与优化路线 | `planner`, `reviewer`, `time_check` |
| 完善旅行细节 | `meal_search`, `meal_recommend`, `spot_tips`, `finalize` |

Run 卡保存 `currentStage` 与已到达阶段集合，而不只保存 `last_event`。循环中的节点不会让步骤倒退。默认展示四阶段 stepper 和当前说明；技术标签仅在可选详情中出现，且不得包含内部推理。

### 7. Run 卡由状态决定主操作

- `queued`：说明已保存并会自动开始；主操作为停止。
- `running`：展示产品阶段与可离开页面的保障；主操作为停止。
- `waiting_user`：问题与结构化输入成为主操作；停止降为次操作。
- `succeeded`：加载或复用权威 itinerary 摘要；主操作为打开完整行程，次操作为继续修改。
- `failed`：显示净化错误与请求保留说明；可重试时创建新 Run。
- `cancelled`：使用中性表达；允许重新开始。

Run ID 默认不显示，只在诊断详情中提供。状态文本、图标和语义标题共同表达，不依赖颜色圆点。

### 8. 普通 composer 与 Run resume 明确分离

默认 composer 始终发送 Conversation Message。用户从等待任务进入回复模式后，composer 上方显示目标任务 chip，或直接使用卡内控件；提交调用 `/api/runs/{id}/resume`，不能同时发送普通消息。

这避免正式规划运行期间的普通聊天被错误解释为恢复回答。

### 9. 运行中请求变更使用显式决策

当消息被识别为针对活动不可变 Run 的新约束时，前端展示决策卡：

- 停止当前任务并使用合并后的 brief 创建新规划；
- 保持当前任务，完成后以结果 itinerary 创建 revision；
- 取消本次变更。

第一版可由现有 `related_run_id`、`related_itinerary_id` 和 Chat 回复引导完成；若后端尚未返回可执行决策事件，则任务中先补充最小安全事件或 action descriptor，而不通过文案猜测自动执行。

### 10. 可访问性作为状态组件契约

异步状态标题使用语义化 heading。仅对关键转变（等待回复、完成、失败）使用礼貌级别 live region，token streaming 与进度动画不逐项播报。认证完成、卡片展开和 resume 失败后执行明确焦点恢复。所有操作使用真实 button/input，保持可见焦点和至少可接受的点击目标。

## Risks / Trade-offs

- **[跨实体时间戳相同导致排序不稳定]** → 使用类型优先级与稳定 ID 兜底，并增加刷新前后排序测试；若仍不足再引入 conversation event sequence。
- **[统一入口影响旧 PlanPage 行为]** → 分阶段切换导航并保留回退路径，先覆盖缺字段、修改和结果打开测试。
- **[后端 input_schema 信息不足]** → 提供安全文本降级；只有明确识别的问题使用高级控件。
- **[结果摘要需要额外请求]** → 仅在成功卡可见时按 itinerary ID 获取并缓存；失败时仍保留“打开完整行程”操作。
- **[多任务摘要占用 composer 空间]** → 默认只显示需要用户操作或最近活动的一项，其余通过可展开任务列表访问。
- **[状态播报过多]** → 只播报关键状态，不播报 token、heartbeat 和每个内部 stage。
- **[识别运行中变更可能不可靠]** → 不自动取消或创建 revision；缺乏明确绑定时继续要求用户选择目标。

## Migration Plan

1. 扩展 `ChatState` 的活动投影、产品阶段和重复事件测试，不改变现有视觉。
2. 建立可访问的 ActivityTimeline、BriefSummary 与 RunCard 状态组件，并保持旧组件可回退。
3. 接入结构化问题、确认摘要、成功预览和活动任务摘要。
4. 调整认证 continuation 与导航，使旅行对话成为唯一默认入口。
5. 完成桌面、移动端、键盘、刷新恢复、多任务和错误回归测试后默认启用新体验。
6. 观察并清理不再被前端调用的旧 PlanPage 入口；后端兼容 API 的删除另行提案。

回滚时恢复旧导航与旧 ChatPage 渲染分支；数据库、Run、Message、Brief 和 Itinerary 数据无需回滚。

## Open Questions

- 是否需要后端提供 conversation 级 activity sequence，还是 `sequence + created_at + stable id` 已能满足真实数据排序？
- 成功卡第一版应请求完整 itinerary 生成摘要，还是新增轻量结果摘要 API？
- 运行中约束变更的决策应由 Chat graph 发出结构化 action event，还是由独立 API 根据绑定目标创建？
- 空状态是否每次创建新 Conversation，还是在当前空对话存在时复用该对话？
