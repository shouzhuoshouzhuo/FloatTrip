# 旅游规划agent（vibecoding项目）（FloatTrip英文名）
# hook
每次在push到github的时候，要给readme文档介绍此次的版本更新内容，类似于changelog
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
目前已经实现的是：

1. 网页内容抓取
   tools/fetch_webpage_content.py
        ↓
2. markdown 信息源
   .md 文件
        ↓
3. markdown 抽取景点候选池
   tools/langgraph_markdown_candidate_pool.py
        ↓
4. 候选景点 JSON
   /tmp/markdown_candidates.json
        ↓
5. 高德 POI 过滤 + 补坐标
   tools/amap_poi_filter.py
        ↓
6. 带 POI 坐标的候选池 JSON
   /tmp/amap_candidates.json
        ↓
7. 按地理距离聚类
   tools/geo_day_cluster.py
        ↓
8. 可视化调试地图
   tools/render_geo_day_clusters_map.py
        ↓
9. 每日公交路线规划 JSON
   tools/plan_daily_transit_routes.py
        ↓
10. 调用高德公交 / 步行路径，生成真实通行时间矩阵与真实 polyline 路径
    - 公交通行时间用于暴力枚举当天最短访问顺序
    - 近距离无公交路线时，用高德步行路径兜底
    - 每段路线输出真实 path，不画简单两点连线
        ↓
11. planner v2 前端路线预览
    static/docs/plannerv2.html
    - 已集成高德 JS 地图
    - 已展示按天路线、访问顺序、公交/步行路段、预算式指标区域雏形
    - 地图中展示的是高德返回的真实行径路线

当前说明：

- tools/render_geo_day_clusters_map.py 仍然只是开发阶段的聚类调试地图。
- 正式前端路线展示入口已经推进到 planner v2，使用高德地图显示规划好的每日路线。
- 后续重点是把这条 tools 链路收敛进正式 Agent / FastAPI / app.floattrip.com 工作台流程，并继续补 LLM 生成自然语言行程、预算拆分、导出和再次生成能力。
还有前端首页已经设计好/Users/chj/Desktop/旅游规划agent/static/docs/indexv1.html
前端的用户页中的规划页也设计好/Users/chj/Desktop/旅游规划agent/static/docs/plannerv2.html
下一步需要用户页的行程详情页 prd是这么写的#### 4. 行程详情页 `app:/trips/:id`

核心功能：

- 查看每日行程
- 查看预算拆分
- 再次生成和导出