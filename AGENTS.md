# 旅游规划agent（vibecoding项目）（FloatTrip英文名）
# hook
每次在push到github的时候，要给readme文档介绍此次的版本更新内容，类似于changelog，对每个版本进行版本编号，changelog要有对应的版本编号和push这个版本的日期，便于后续追溯
# 总揽
这个项目是一个旅游规划agent，产品宗旨是让旅游规划像水面一样自然浮动出来，让用户舒适的，顺滑的，如同全身放松自然浮动在平静的水面上的感觉，体验到一键旅游规划的快感
# 前端设计宗旨
用户使用起来如同浮动在平静的水面上，感受到全身放松的感觉，现代柔和前端、淡蓝渐变光感、悬浮水面感、弱分割线、强交互动效
# 后端技术栈
agent编排：langgraph｜langchain
agent测试 and 迭代：langsmith
后端 ： fastapi
# rules
站点入口约定：

官网前台：www.floattrip.com
用户工作台：app.floattrip.com
后台管理台：admin.floattrip.com
要求后端的文件都有文档级别注释和函数级别注释，中文注释，并且要求写清楚功能，参数，返回值
# agent 设计
规划agent，配备有tools：定位，查询
第一版规划采用，网页搜索汇总候选景点池，先只用出现次数做一个排名打分，
候选景点打分
  ↓
按区域聚类分天
  ↓
每天选 2～4 个景点
  ↓
调用高德得到交通时间矩阵
  ↓
暴力枚举 / 2-opt 求当天最短访问顺序
  ↓
LLM 生成自然语言行程




