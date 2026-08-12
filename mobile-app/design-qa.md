# 轻舟移动端对话修复 Design QA

## 验证环境

- iPhone 17 模拟器，iOS 26.5
- React Native Debug + Metro 8081
- 后端 FastAPI 本地接口

## 核心检查

- [x] 规划首页提供明确的“历史对话”入口
- [x] 历史对话展示继续对话、后台规划、等待确认、条件齐全和未读完成状态
- [x] 从历史列表重新打开后，恢复持久化消息、Planning Brief 和当前 Run
- [x] 离开对话页面只断开客户端 SSE，不取消服务端规划；重新进入会按 conversation_id 恢复
- [x] Chat Run 与 Travel Plan Run 在界面状态上分离
- [x] 输入“南京3日游”后显示必要追问，不进入深度规划
- [x] 缺少开始/结束日期时隐藏“开始规划”按钮
- [x] 提交前再次从服务端读取最新 Brief，仅 `ready` 且必要字段齐全时允许规划
- [x] 视觉沿用现有浅灰背景、天空蓝强调、大圆角卡片和紧凑移动端密度
- [x] 安全区、顶部返回、固定输入框和滚动状态正常

## 自动化结果

- TypeScript: passed
- Jest: 12/12 passed
- ESLint: passed（仅保留原项目 warnings）
- iOS production JS bundle: passed
- FastAPI runtime API/streaming: 14/14 passed

## 现场验证截图结论

- 历史列表能够呈现并进入历史对话。
- 历史“南京3日游”恢复后，界面明确显示“缺少开始日期、结束日期”，且不存在开始规划按钮。

final result: passed
