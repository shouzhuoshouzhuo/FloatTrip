# 途见 · FloatTrip：让旅行规划从一次回答，变成可协作的决策过程

> **记住旅行偏好，从一句话走到可执行行程。**
>
> 途见（FloatTrip）是一个基于 LangGraph 的多 Agent 旅行规划项目。它会先通过对话理解你的出行条件，再结合可控的旅行记忆、高德真实 POI 与天气数据，生成可追踪、可编辑的逐日行程。

[查看项目主页](https://github.com/shouzhuoshouzhuo/FloatTrip) · [了解运行时架构](https://github.com/shouzhuoshouzhuo/FloatTrip/blob/main/docs/agent-runtime.md)

---

## 旅行规划，难的不只是“写一份攻略”

很多旅行工具都能根据一句提示生成一份看上去不错的清单，但真正落地时，问题往往才刚开始：

- **偏好不会被延续**：这次说过不吃辣、喜欢慢节奏，下次规划又要从头解释。
- **建议未必真实可去**：语言模型可能编造地点，或忽略天气、地理距离与开放时间。
- **路线不一定合理**：景点各自都不错，却可能被安排成跨城折返的一天。
- **结果难以继续协作**：用户临时想换点、改时段或删掉一天，往往只能重新生成整份行程。

途见希望解决的不是“帮你多写一篇攻略”，而是把旅游规划变成一个**可理解、可确认、可校正、可继续编辑**的过程：系统记得什么、为什么这样安排、哪里正在校验，都不应该是黑盒。

---

## 为什么不是一个万能 Agent？

旅行规划同时是一个需求理解、信息检索、约束满足和体验设计问题。若让一个 Agent 一次性处理所有事，它既要理解用户口语，又要回忆历史偏好、查找真实地点、排路线、检查冲突、输出餐饮与贴士；上下文容易混杂，出错后也很难知道该由哪里修正。

途见把任务拆给职责明确的 Agent 和数据层：**生成者不只自己评自己，真实数据不交给模型凭记忆编造，用户也不必在错误的前提上等待完整规划。**

这不是为了增加 Agent 数量，而是为了让每一步都能有清晰的输入、输出与纠错边界。相应地，系统也承担了更多协调和调用成本，因此只在确有价值的节点引入循环与校验，并通过有限轮次控制响应时间。

<p align="center">
  <img src="https://raw.githubusercontent.com/shouzhuoshouzhuo/FloatTrip/main/static/images/readme/agent-orchestration-labeled-v2.png" alt="多 Agent 旅行规划编排图：用户对话和旅行记忆汇入确认关卡，天气与 POI 数据辅助规划 Agent，规划 Agent 与评审 Agent 双向校正，时间核查回流后再生成餐饮、贴士和可编辑地图行程" width="100%" />
</p>

<p align="center"><sub>从用户画像到可编辑行程：每个环节只处理它最擅长、也最需要被验证的事情。</sub></p>

---

## 多 Agent 如何协作：职责分工与设计权衡

| 角色 / 阶段 | 它负责什么 | 为什么这样分工 | 取舍 |
| --- | --- | --- | --- |
| **对话理解 + Planning Brief** | 从自然语言中提取目的地、日期、同行人和约束，并把关键信息展示为确认卡。 | 先确认问题，再消耗正式规划资源；避免在日期或目的地都不完整时生成一整份错误行程。 | 多一次确认交互，换来更低的返工成本与更明确的用户意图。 |
| **Query Rewrite** | 将用户授权的旅行画像投影到本次查询中。 | 历史偏好应帮助规划，而不是覆盖本次诉求；当前对话始终优先。 | 需要维护记忆来源、作用域与冲突规则，不能把“记住”做成不可控的猜测。 |
| **真实数据层：天气 + 高德 POI** | 提供天气、候选景点和周边餐饮的真实数据。 | 地点必须来自候选池，不能仅依赖模型知识；天气也应成为路线条件而非附加文案。 | 引入外部服务依赖，并将可选范围限制在搜索结果中，换来更可验证的可执行性。 |
| **Planner Agent** | 综合日期、偏好、天气、候选地点与地理位置，编排逐日游玩顺序。 | 让它专注“设计体验”和组织行程，而不是同时承担所有审查任务。 | Planner 可能仍然做出不理想安排，因此它不是最终裁决者。 |
| **Reviewer Agent** | 独立审阅动线、候选池约束、节奏和需求响应，并给出可执行的修改意见。 | 生成与评审分离，可以发现 Planner 的盲点，且反馈会沉淀到下一轮。 | 额外调用会增加等待时间；系统采用有限轮次循环，在质量与成本之间取平衡。 |
| **Time Check Agent** | 专项核查开放时间、闭馆日和时间槽冲突，再把定向问题交回 Planner。 | 将这类事实校验从 Reviewer 中拆出，避免多个角色对同一类问题重复干预、反馈震荡。 | 多一个节点，但能让 Reviewer 保持关注路线体验，让时间冲突有专门的修正回路。 |
| **餐饮推荐 + 游玩贴士** | 在路线稳定后，为每天补齐周边餐饮和到访建议。 | 先稳定主路线，再处理可替换的细节，避免提前计算在后续路线调整中失效。 | 结果生成更分阶段，但主流程更聚焦、局部失败也不影响核心行程。 |
| **Finalize + 持久化 Runtime** | 收敛时刻表、距离、地图与约束说明；保存进度、结果和交互状态。 | 用户需要知道规划进行到哪里，也需要在断线、取消或修改后继续工作。 | 当前实时调度面向单节点部署；横向扩展需额外引入分布式队列与事件流。 |

### 一条受控的校正回路

规划不是一次生成后就结束。Planner 先给出路线，Reviewer 检查是否真正满足需求并指出问题；若需要修正，Planner 根据反馈重排。主循环收敛后，Time Check 再专门核对开放时间与闭馆日；只有发现事实冲突时，才把问题定向送回 Planner。

这种分工刻意避免两种极端：既不让一个“万能 Agent”独自决定一切，也不让多个 Agent 对同一问题无限循环。最终结果会在有限轮次内收敛，再进入餐饮、贴士和行程收敛阶段。

---

## 个性化不是标签堆砌，而是可控的上下文

途见将个性化拆成两层：**长期旅行画像**和**本次出行约束**。

长期画像可以沉淀你确认过的偏好与避雷项，例如慢节奏、亲子友好、不吃辣或偏好博物馆；本次对话则决定这一次去哪里、什么时候去、同行人是谁，以及是否要临时改变偏好。系统明确让当前需求优先，临时覆盖不会静默污染长期记忆。

每条记忆都带有来源和作用域，用户可以查看、编辑、新增或忘记它。这让“系统记得你”不再是一个不可解释的承诺，而是一个由用户掌控的工具。

<p align="center">
  <img src="https://raw.githubusercontent.com/shouzhuoshouzhuo/FloatTrip/main/static/images/readme/conversation-memory-brief.png" alt="途见的对话确认与记忆感知 Planning Brief：目的地、日期和本次带入的旅行偏好会在启动规划前清晰展示" width="100%" />
</p>

<p align="center"><sub>先把旅行条件说清楚：Planning Brief 让用户决定何时启动正式规划。</sub></p>

<p align="center">
  <img src="https://raw.githubusercontent.com/shouzhuoshouzhuo/FloatTrip/main/static/images/readme/travel-memory-profile.png" alt="途见的旅行画像页面，展示可管理的偏好、避雷项、来源和作用范围" width="100%" />
</p>

<p align="center"><sub>旅行画像可追溯、可编辑、可忘记，而不是黑盒画像。</sub></p>

---

## 让方案从“看起来不错”走向“可以出发”

当用户确认 Planning Brief 后，规划流程才会启动。天气与真实 POI 进入候选池，Planner 按天组织路线，Reviewer 与 Time Check 分别承担体验审阅和事实核验。最终，系统会把结果呈现为带时间表、餐饮建议、距离和地图动线的行程，而不是一段难以使用的长文本。

<p align="center">
  <img src="https://raw.githubusercontent.com/shouzhuoshouzhuo/FloatTrip/main/static/images/readme/itinerary-map.png" alt="途见的行程详情页面：每日时间表、候选地点、餐饮建议和地图动线在同一视图联动" width="100%" />
</p>

<p align="center"><sub>真实地点、地图动线和逐日安排放在同一视图中，方便判断行程是否合理。</sub></p>

行程生成后仍可继续协作：用户可以拖拽调整顺序、替换地点、修改时段、撤销重做，或让系统重新优化路线。对于已有行程的修改，系统会从已有状态恢复，聚焦 Planner 与 Reviewer 的局部校正，而非粗暴地从头再来。

---

## App 端：把规划过程带到旅途中

FloatTrip 同时提供与 FastAPI 后端直接联调的 React Native App（iOS / Android）。移动端不是网页截图的简单封装：对话、Planning Brief、持久化规划进度、旅行画像与地图行程都复用同一套后端能力。

<table>
  <tr>
    <td width="25%" valign="top">
      <img src="https://raw.githubusercontent.com/shouzhuoshouzhuo/FloatTrip/main/static/images/readme/mobile/app-home.png" alt="FloatTrip App 对话式旅行规划首页" width="100%" />
      <p align="center"><b>一句话开始规划</b></p>
    </td>
    <td width="25%" valign="top">
      <img src="https://raw.githubusercontent.com/shouzhuoshouzhuo/FloatTrip/main/static/images/readme/mobile/app-planning-brief.png" alt="FloatTrip App 的 Planning Brief 确认卡" width="100%" />
      <p align="center"><b>确认本次出行条件</b></p>
    </td>
    <td width="25%" valign="top">
      <img src="https://raw.githubusercontent.com/shouzhuoshouzhuo/FloatTrip/main/static/images/readme/mobile/app-live-planning.png" alt="FloatTrip App 实时展示多 Agent 规划进度" width="100%" />
      <p align="center"><b>实时查看规划进度</b></p>
    </td>
    <td width="25%" valign="top">
      <img src="https://raw.githubusercontent.com/shouzhuoshouzhuo/FloatTrip/main/static/images/readme/mobile/app-map-itinerary.png" alt="FloatTrip App 的地图联动行程" width="100%" />
      <p align="center"><b>地图联动的可编辑行程</b></p>
    </td>
  </tr>
</table>

无论在桌面端还是 App 端，用户看到的都不是一个等待结束的黑盒：从确认条件、启动规划到获得可编辑路线，每一步都可以被理解、追踪与继续修改。

---

## 一起把旅行规划做得更可靠

途见仍在持续完善中。我们尤其欢迎对 Agent 编排、旅行体验设计、地图数据、移动端交互和运行时可靠性有兴趣的开发者参与。

- 前往 [FloatTrip 项目主页](https://github.com/shouzhuoshouzhuo/FloatTrip) 了解完整技术栈与运行方式。
- 阅读 [Agent Runtime 说明](https://github.com/shouzhuoshouzhuo/FloatTrip/blob/main/docs/agent-runtime.md)，了解持久化 Run、SSE 回放与单节点边界。
- 欢迎为 [FloatTrip 点亮 Star](https://github.com/shouzhuoshouzhuo/FloatTrip/stargazers)、提交 [Issue](https://github.com/shouzhuoshouzhuo/FloatTrip/issues)，或通过 [Pull Request](https://github.com/shouzhuoshouzhuo/FloatTrip/pulls) 参与贡献。

如果你也相信旅行规划应该记得用户、尊重现实、允许持续修改，欢迎访问 [https://github.com/shouzhuoshouzhuo/FloatTrip](https://github.com/shouzhuoshouzhuo/FloatTrip)，**Star、提 Issue、Contribute**，一起把 FloatTrip 做得更好。
