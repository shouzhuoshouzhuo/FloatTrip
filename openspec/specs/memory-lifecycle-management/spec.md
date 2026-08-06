# memory-lifecycle-management Specification

## Purpose
Define durable extraction, conservative migration, review, approval, archival finalization, retry, and user management of travel memories.

## Requirements

### Requirement: Conversation archive is read-only and eventually finalized
系统 SHALL 允许用户显式归档 Conversation，归档操作 SHALL 幂等、立即禁止新消息，并异步提取剩余长期记忆。

#### Scenario: Archive an active conversation
- **WHEN** 用户归档自己拥有的 active Conversation
- **THEN** Conversation 立即变为 archived，创建唯一 archive 提取任务并返回 pending finalization 状态

#### Scenario: Send to an archived conversation
- **WHEN** 用户尝试向 archived Conversation 发送消息
- **THEN** 系统返回 `409 conversation_archived`

### Requirement: Extraction jobs are durable and retryable
系统 SHALL 持久化提取范围、状态和尝试次数，MUST 保证同一范围幂等，并 SHALL 支持失败任务重试。

#### Scenario: Process restarts during extraction
- **WHEN** 服务在任务 running 时退出并重新启动
- **THEN** 遗留任务可重新进入 pending 并从持久化消息安全重放

### Requirement: Users manage active and candidate memories
系统 SHALL 提供查看、创建、替代编辑、批准候选和软删除记忆的所有者隔离 API 与界面。

#### Scenario: Approve an inferred candidate
- **WHEN** 用户在画像页批准自己拥有的 candidate
- **THEN** 事实变为 active、revision 递增，并可被新 Conversation 冻结

#### Scenario: Access another user's memory
- **WHEN** 用户读取或修改另一用户的 memory fact
- **THEN** 系统拒绝操作且不暴露事实内容

### Requirement: Legacy profile migration is conservative
系统 SHALL 幂等迁移旧三类偏好为 active facts，并 SHALL 把旧 visited destinations 迁为 candidate 而不是已确认访问历史。

#### Scenario: Application starts with legacy profile rows
- **WHEN** 旧 `user_profiles` 存在尚未迁移的数据
- **THEN** 系统创建不重复的新事实并停止从旧表读写画像
