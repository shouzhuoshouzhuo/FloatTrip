# Agent Runtime 运行说明

## 架构边界

依赖方向固定为：

```text
FastAPI / SSE
      ↓
Application Services
      ↓
Agent Runtime ─────→ SQLite / LangGraph Checkpointer
      ↓
Chat Graph / Planning Graph
```

`app/chat` 与 `app/planning` 不允许导入 FastAPI、`StreamingResponse` 或前端协议。
图只产生 LangGraph `messages`、`custom` 和内部状态更新；`app/runtime` 负责验证、
持久化和投影公开事件，`app/api` 负责 HTTP/SSE 编码。

## 默认配置

| 环境变量 | 默认值 | 含义 |
|---|---:|---|
| `RUNTIME_CHAT_CONCURRENCY` | 8 | 同时运行的 Chat Run 上限 |
| `RUNTIME_PLANNING_CONCURRENCY` | 2 | 全局正式规划/修改 Run 上限 |
| `RUNTIME_PLANNING_PER_USER` | 2 | 单用户正式规划/修改上限 |
| `RUNTIME_LLM_CONCURRENCY` | 8 | LLM 调用容量 |
| `RUNTIME_AMAP_CONCURRENCY` | 8 | 高德调用容量 |
| `RUNTIME_CHECKPOINT_DB` | `data/langgraph-checkpoints.db` | LangGraph SQLite checkpoint 文件 |
| `CHAT_CONTEXT_BUDGET_TOKENS` | 3000 | Chat 最终上下文预算 |
| `CHAT_SUMMARY_TRIGGER_TOKENS` | 2600 | 触发累计摘要的估算 token 阈值 |
| `CHAT_SUMMARY_TARGET_TOKENS` | 600 | 结构化摘要目标大小 |
| `CHAT_RECENT_TURNS` | 6 | 压缩后保留的完整最近轮次 |
| `CHAT_MAX_MESSAGE_TOKENS` | 1200 | 单条用户消息预算 |
| `CHAT_SUMMARY_MODEL` | 当前 provider 默认模型 | 可选摘要模型覆盖 |
| `MEMORY_EXTRACTION_MODEL` | 当前 provider 默认模型 | 可选长期记忆提取模型覆盖 |
| `MEMORY_EXTRACTION_INPUT_TOKENS` | 6000 | 归档提取的单批输入预算 |

SQLite 主库启用 WAL 与 30 秒 busy timeout。Run 事件序列在单个 Run 内单调递增；
生命周期、进度、等待交互、错误、最终消息和结果关联为持久事件，token delta 与
heartbeat 默认只走实时通道。

## 恢复行为

- `queued` Run 在单节点进程启动后重新进入确定性队列。
- 无本地协程且没有可证明安全恢复路径的 `running`/`waiting_user` Run 会被标记为
  可重试失败，避免永久卡住。
- LangGraph interrupt 使用 `run_id` 作为稳定 `thread_id`。恢复必须同时匹配
  `run_id` 和当前 `interaction_id`，然后发送 `Command(resume=...)`。
- SSE 重连先建立实时订阅，再按 `after_seq`/`Last-Event-ID` 回放持久事件，最后
  按序去重切换到实时流。

## 并发与一致性

- Chat：`chat:{conversation_id}`，同一会话串行。
- 新规划：`plan:{run_id}`，彼此独立并受用户/全局容量约束。
- 行程修改：`revision:{itinerary_id}`，同一基础行程严格串行并生成新版本。
- 正式规划任务达到容量时仍可创建，状态保持 `queued`；Chat 使用独立容量，不被
  长规划挤占。

## 单节点限制

当前实时通知、协程任务句柄和信号量位于进程内，不提供多节点任务领取、
exactly-once 执行或跨节点 SSE fan-out。若部署多个应用实例，需要引入外部任务
队列/租约、共享事件流和分布式并发控制；在完成这些工作前应保持单节点运行。

## 观测

认证用户可读取 `/api/runtime/metrics`，其中包括排队时长、运行时长、各类型活动
Run、终态计数、失败原因、provider 容量，以及会话估算 token、摘要/提取结果和归档
整理延迟。Runtime 同时输出 JSON 结构化日志；记忆日志只记录 conversation、revision、
序列范围、计数和状态，不记录事实正文或原始消息。
