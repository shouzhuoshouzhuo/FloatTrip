## Context

Conversation 侧栏当前只读取 `conversations` 基础字段。正式规划 Run 即使在其他会话后台运行、进入 `waiting_user` 或已经成功，侧栏也没有状态；前端切换会话后还会停止原会话 SSE，因此不能只依赖当前页面内的 Run state。系统已有持久化 Runs、PlanningBrief 和会话所有权，可以由列表查询统一聚合。

## Goals / Non-Goals

**Goals:**

- 让会话列表可靠表达正式规划的“待处理、规划中、完成未读”状态。
- 未读状态刷新后仍保留，并只在用户实际查看可见会话时清除。
- 状态在切换会话后仍能通过轻量轮询及时更新。
- 保持现有手账视觉、键盘可访问性和窄侧栏可读性。

**Non-Goals:**

- 不接入系统级推送、邮件或浏览器 Notification API。
- 不为普通 Chat 回复建立逐消息未读计数。
- 不改变 Run 调度、取消或归档语义。

## Decisions

### 1. 服务端聚合关注状态

`GET /api/conversations` 基于每个会话的 Runs 与 PlanningBrief 返回布尔状态：`has_active_planning`、`has_waiting_user`、`has_ready_brief`、`has_unread_completed`。只统计 `travel_plan/revision`，Chat Run 不产生规划提醒。这样不同前端和刷新后的语义一致，避免客户端扫描所有 Run。

### 2. 使用 `last_viewed_at` 作为持久化查看游标

`conversations.last_viewed_at` 记录用户最后一次真正查看该会话的时间。成功 Run 的 `finished_at/updated_at` 晚于此游标时即为未读。新增 `POST /api/conversations/{id}/view`，必须校验所有权并幂等更新时间。相比本地存储，该方案支持刷新和跨设备一致性。

### 3. 只有可见页面才标记已查看

前端在会话内容加载完成且 `document.visibilityState === "visible"` 时调用 view 接口；正式 Run 在当前可见会话内成功时再次标记。后台标签页不会仅因轮询或 SSE 自动清除未读，窗口重新可见时立即同步并标记当前会话。

### 4. 关注状态优先级固定

侧栏单条会话按 `waiting_user > ready_brief > active_planning > unread_completed > none` 展示主状态：分别为“待你回复”“待确认”“规划中”“新行程”。待处理优先于加载态，避免用户错过需要操作的任务；归档会话只显示归档状态。

### 5. 轻量可见轮询

登录后每 4 秒刷新 Conversation 列表；页面隐藏时跳过请求，重新可见时立即刷新。当前会话的 Run 事件仍负责主内容实时性，轮询只服务跨会话侧栏。

## Risks / Trade-offs

- **[时间戳并发边界]** → view 更新与完成事件均使用服务端 UTC；比较成功 Run 的终态时间，避免客户端时钟参与。
- **[旧会话全部变未读]** → 迁移时将已有记录的 `last_viewed_at` 回填为 `updated_at`。
- **[频繁列表查询]** → 使用 EXISTS 子查询和 Runs/Brief 现有索引，页面隐藏时停止轮询。
- **[当前会话完成瞬间短暂出现未读]** → 可见页面收到终态后立即 mark viewed；最多出现一个轮询周期的短暂状态。

## Migration Plan

1. 幂等增加 `last_viewed_at` 并回填历史会话。
2. 上线聚合列表与 view API。
3. 上线前端状态标识、可见性处理和轮询。
4. 回滚时前端忽略新增字段；数据库列可保留，不影响旧版本。

## Open Questions

无。
