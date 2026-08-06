## 1. 数据模型与迁移

- [x] 1.1 添加 Conversation 归档字段、记忆状态、事实、revision 和提取任务表及索引
- [x] 1.2 实现旧 `user_profiles` 到结构化事实的幂等迁移，并启用 SQLite 外键
- [x] 1.3 实现事实、会话记忆和提取任务仓库及所有者隔离

## 2. Chat 短期记忆

- [x] 2.1 修复最新消息查询并在首条消息事务中冻结长期记忆快照
- [x] 2.2 实现 token 估算、结构化累计摘要 schema 和压缩服务
- [x] 2.3 按 System/Memory/Summary/Application/History/Current 顺序重构 Chat Prompt
- [x] 2.4 增加单消息预算校验、摘要失败降级和记忆观测字段
- [x] 2.5 增加 active Conversation 主动压缩服务与幂等 API

## 3. 长期事实提取

- [x] 3.1 实现严格提取 schema、旅游作用域、敏感信息和证据校验规则
- [x] 3.2 实现持久提取 worker、幂等写入、替代、遗忘和重试
- [x] 3.3 接入压缩前与归档提取，并在 Runtime 生命周期启动/停止 worker

## 4. API 与规划衔接

- [x] 4.1 实现 Conversation 归档、归档重试和 archived 写保护 API
- [x] 4.2 用事实式 Profile/Memory API 替换四列表画像 API
- [x] 4.3 让 Conversation 规划复用冻结快照，独立规划在创建时冻结最新事实
- [x] 4.4 停止生成行程时自动写入 `visited_destinations`

## 5. 前端体验

- [x] 5.1 更新 API client、归档入口、只读 composer 和整理状态
- [x] 5.2 把画像页改造成 active facts 与 candidate facts 管理界面
- [x] 5.3 补充记忆卡片、作用域、状态和响应式样式
- [x] 5.4 增加主动压缩按钮、忙碌态和结果反馈

## 6. 验证

- [x] 6.1 添加 201+ 消息、冻结快照、压缩和 Prompt 优先级测试
- [x] 6.2 添加迁移、事实生命周期、敏感信息、归档和后台重试测试
- [x] 6.3 添加 API、规划快照和前端状态回归测试并运行完整测试套件
- [x] 6.4 添加主动压缩、短会话幂等和归档写保护回归测试
