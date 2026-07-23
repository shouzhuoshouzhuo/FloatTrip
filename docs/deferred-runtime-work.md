# Agent Runtime 延期项

以下工作超出当前单节点 OpenSpec change 的范围，不影响本次实现的验收：

- 多节点任务领取、租约续期与故障转移。
- Kafka、RabbitMQ、Celery 或 Redis Streams 等外部任务/事件基础设施。
- 跨节点 SSE fan-out 与分布式 concurrency key。
- exactly-once 执行保证；当前通过幂等提交、不可变快照和可见失败提供
  at-least-once 场景下的安全边界。
- 大规模历史 RunEvent/Checkpoint 的分区、归档与自动压缩策略。
- 基于真实 provider 配额和生产流量的长时间压力测试与容量调优。
- 将运行指标接入 Prometheus/OpenTelemetry；当前提供进程内聚合指标与 JSON 日志。
