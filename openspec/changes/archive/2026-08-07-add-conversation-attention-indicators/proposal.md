## Why

旅行规划会在后台持续执行，但当前会话侧栏只展示标题和日期，用户无法判断哪个对话仍在规划、哪个正在等待自己确认，也容易错过已经完成但尚未查看的行程结果。需要让侧栏成为可靠的任务收件箱，而不只是历史列表。

## What Changes

- 为 Conversation 持久化最后查看时间，并由服务端聚合正式规划 Run、待用户交互和 ready PlanningBrief 的关注状态。
- 会话侧栏展示三类互不混淆的状态：规划中加载图标、待确认/待回复提醒、完成未读提醒。
- 用户实际打开且页面可见时标记会话已查看；后台标签页和仅轮询列表不会错误清除未读。
- 前端定期刷新轻量会话列表，使切换到其他对话后仍能获知后台规划状态变化。
- 历史数据迁移时默认视为已查看，避免上线后把所有旧行程标记为未读。

## Capabilities

### New Capabilities

- `conversation-attention`: 定义会话查看游标、规划状态聚合、提醒优先级和侧栏交互行为。

### Modified Capabilities

无。

## Impact

- 数据库：`conversations` 增加 `last_viewed_at`，并进行兼容回填。
- 后端：Conversation repository/list API、新增 mark-viewed API。
- 前端：会话列表状态投影、轮询、可见性处理、加载与提醒样式。
- 测试：状态聚合、跨用户隔离、未读清除、前端优先级及真实页面视觉回归。
