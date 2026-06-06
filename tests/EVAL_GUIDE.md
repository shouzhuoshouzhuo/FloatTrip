# Planner⇄Reviewer 评估框架使用手册

这套框架用来评估 **planner** 和 **reviewer** 两个 Agent 的质量：
在各种目的地、出行时间、天气、偏好下，能否在 3 轮以内产出合格规划？

---

## 目录结构

```
tests/eval/
  fixtures/           ← 测试用例（每个 .json 一个用例，数据集在这里管理）
  graders/
    code_graders.py   ← 确定性打分器 G1–G7（复用生产的 helpers.py）
    llm_judge.py      ← LLM 评委（主观质量打分）
    reviewer_reliability.py  ← reviewer 可靠性 + planner 反驳率
  harness.py          ← 从 fixture 构造状态并跑 planner⇄reviewer 循环
  run_eval.py         ← 主入口，加载用例 → 跑 k 次 → 打分 → 报告
  report.py           ← 指标聚合与 Markdown 报告
  capture_pool.py     ← 一次性工具：调高德 API 抓真实景点池骨架

tests/EVAL_GUIDE.md   ← 本文件
tests/eval/transcripts/   ← 运行后自动生成，存每个用例最后一次的 route/对话记录
```

---

## 快速开始

```bash
# 0. 确保 .env.local 已配置 AMAP_API_KEY 和 DEEPSEEK_API_KEY

# 1. 冒烟：单个用例跑 1 次，只跑代码打分（不调 LLM 评委，省钱省时）
python -m tests.eval.run_eval --only nanjing-3d-sunny-history --k 1 --no-judge

# 2. 标准评估：所有用例，k=5
python -m tests.eval.run_eval --k 5

# 3. 输出 Markdown 报告
python -m tests.eval.run_eval --k 5 --out report.md
```

---

## 指标解读

报告的每一列：

| 指标 | 含义 | 好的方向 |
|---|---|---|
| **pass 率** | k 次中客观通过且收敛的比例 | 越高越好 |
| **pass@k** | k 次中≥1 次通过（能力下界） | 1 = 具备能力 |
| **pass^k** | k 次全部通过（可靠性） | 1 = 稳定可靠 |
| **轮次均值** | 平均用了几轮才通过或达上限 | 越低越好，目标 ≤ 3 |
| **误放行** | reviewer 通过但代码打分客观未过 | 应接近 0% |
| **误打回** | reviewer 打回但代码打分客观已合格 | 应接近 0% |
| **反驳率** | planner 反驳 reviewer 意见的比例 | 视情况，结合 pass 率看 |
| **忽略率** | planner 既不改也不解释的比例 | 越低越好，忽略≈掩盖问题 |
| **评委均分** | LLM 评委主观打分的 5 维平均（1-5 分） | 越高越好，≥4 算合格 |

**代码打分 G1–G7**（每次 trial 都会打）：

| 代号 | 检查内容 | 失败含义 |
|---|---|---|
| G1 封闭池 | 所有景点必须来自候选池 | planner 幻觉景点，硬性失败 |
| G2 开放时间 | 游玩时段须在景点开放时间内 | 行程不可行 |
| G3 地理跨度 | 每天最大跨度 ≤ `max_day_span_km`（默认 15km） | 路线过于分散 |
| G4 结构合法 | 景点数 ≤ max_per_day；时段有序；evening 景点须夜间开放 | 基本结构问题 |
| G5 覆盖 | 天数匹配、每天非空 | 规划不完整 |
| G6 天气合规 | 雨雪天的露天景点数 ≤ 阈值（依赖 fixture 的 `indoor` 标签） | 未响应天气 |
| G7 收敛 | `approved=True` 且用轮次 ≤ `max_review_rounds` | 未在限制内收敛 |

`objective_pass`（客观通过）= G1–G6 全过；`overall_pass`（最终通过）= 客观通过 ∧ G7 收敛。

---

## 数据集：如何获取和管理 Fixture

### fixture 结构

每个 `.json` 文件是一个独立用例，冻结了 planner 的所有输入（景点池 + 天气），让评估可复现：

```json
{
  "id":          "nanjing-3d-rainy-history",   // 唯一 ID，同时是文件名
  "tier":        "capability",                 // 见下
  "destination": "南京",
  "travel_start_date": "2026-06-10",
  "travel_end_date":   "2026-06-12",
  "days": 3,
  "attraction_preference": "历史古迹、博物馆",
  "habit_preference":      "不喜欢早起，慢节奏",
  "max_per_day":      3,
  "min_rating":       4.5,
  "max_review_rounds": 3,
  "pois": [
    {
      "name": "南京博物院",
      "rating": 4.7,
      "location": {"lat": 32.04, "lng": 118.84},
      "open_time": "09:00-17:00",
      "photo": null,
      "indoor": true          // ← 你需要手工标注的字段（见下）
    }
  ],
  "weather_forecast": [
    {"date": "2026-06-10", "day_weather": "晴",  "night_weather": "晴",
     "day_temp": "30", "night_temp": "22", "is_bad": false},
    {"date": "2026-06-11", "day_weather": "中雨", "night_weather": "小雨",
     "day_temp": "24", "night_temp": "19", "is_bad": true}
  ],
  "expectations": {
    "max_day_span_km":       15,   // G3 阈值
    "outdoor_on_bad_day_max": 0    // G6 阈值：雨天露天景点上限
  }
}
```

**tier 的区别**：
- `regression`：基准用例，条件宽松、景点池充裕，**预期 pass 率接近 100%**。用来防退步。
- `capability`：能力挑战用例，有天气、偏好、景点池受限等困难。**预期通过率低**，作为提升目标。

### 方式一：用脚本自动抓（推荐起步）

会真实调高德 API 取一次景点池，生成骨架 JSON：

```bash
python -m tests.eval.capture_pool \
  --dest  南京         \   # 目的地
  --days  3            \   # 旅行天数
  --start 2026-06-10   \   # 出发日期
  --pref  "历史古迹"    \   # 景点偏好
  --habit "不喜欢早起"  \   # 游玩习惯
  --id    nanjing-3d-history \  # fixture ID（同时是文件名）
  --tier  capability
```

执行后在 `fixtures/nanjing-3d-history.json` 生成骨架。**生成后必须手工完成两件事**：

**① 标注 `indoor` 字段**（G6 天气合规的判断基础）

高德 API 没有室内/室外字段，需要你判断后填写：
- 博物馆、纪念馆、展览馆 → `"indoor": true`
- 公园、山岳、街区、城墙、湖景 → `"indoor": false`
- 不确定可以先填 `null`（G6 会跳过该景点，提示"未标注"）

**② 编辑 `weather_forecast` 构造测试场景**

真实天气预报只有 ~4 天，且今天之后变化，无法复现。需要手工把天气改成你想测试的场景：

| 场景 | 修改方式 |
|---|---|
| 全晴正常 | 所有 `"is_bad": false` |
| 单日雨 | 第 2 天改 `"is_bad": true`, `"day_weather": "中雨"` |
| 全程雨 | 所有天 `"is_bad": true` |
| 酷暑高温 | `day_temp` 改成 "38"，天气字段填 "晴热" |

### 方式二：完全手写

适合精确控制场景的负样本（如"景点池里只有露天景点却全是雨天"这种专门刁难 planner 的边界测试）。直接复制已有 fixture 修改即可。

### 推荐的数据集矩阵（约 20–30 例）

| 维度 | 覆盖目标 |
|---|---|
| 目的地形态 | 密集城市（上海）/ 分散型（丽江/三亚）/ 小城（景德镇）/ 南京基准 |
| 出行天数 | 1 天 / 3 天 / 5 天 |
| 天气 | 全晴 / 单日雨 / 全程雨 / 超预报范围（手写空 forecast） |
| 偏好 | 历史古迹 / 自然户外 / 夜景（考验 evening 时段）/ 慢节奏不早起 |
| 负样本 | 景点池极小（< days×max_per_day）/ 雨天全是露天景点池 / 开放时间普遍偏紧 |

---

## 评估工作流

### 第一次跑（搭建基线）

```bash
# 1. 单个回归用例，k=1，只代码打分，确认框架跑通
python -m tests.eval.run_eval --only nanjing-3d-sunny-history --k 1 --no-judge

# 2. 加 LLM 评委
python -m tests.eval.run_eval --only nanjing-3d-sunny-history --k 1

# 3. 跑能力用例（雨天）
python -m tests.eval.run_eval --only nanjing-3d-rainy-history --k 1
```

### 读 transcript（发现问题时必做）

每次运行会在 `tests/eval/transcripts/<id>.json` 落盘最后一次 trial 的 route + 对话：

```bash
cat tests/eval/transcripts/nanjing-3d-sunny-history.json
```

读 transcript 的目的（Anthropic 建议："Read the transcripts"）：
- 失败的 trial 是 **Agent 的真实问题**，还是 **打分器的误判**？
- 代码打分器报 G4 结构问题，看看那个景点的安排是否真的有问题
- reviewer 打回了，但你看 route 其实挺合理 → 说明 reviewer 误打回率高

如果发现是打分器误判，**修的是 fixture 或打分器**，而不是 Agent。

### 正式评估（k=5）

```bash
python -m tests.eval.run_eval --k 5 --out eval_report.md
```

成本参考（DeepSeek-v4-flash）：每个用例每次 trial 约消耗 3-5 次 LLM 调用（含 planner/reviewer/评委/反驳分析），k=5、20 个用例约 300–500 次调用。

---

## 看指标怎么判断问题在哪

**`pass 率` 低，`误放行` 高**
→ reviewer 放过了不合格方案，reviewer 的判断力有问题。调整 `REVIEWER_SYSTEM` prompt，或降低 `max_review_rounds`。

**`pass 率` 低，`误打回` 高**
→ reviewer 太严，打回了合格方案，浪费轮次。检查 G3/G4 的阈值是否过紧，或者 reviewer prompt 需要调宽。

**`pass 率` 低，`忽略率` 高**
→ planner 不响应 reviewer 意见，建议在 `PLANNER_SYSTEM` prompt 里加强"必须逐条回应 Reviewer 意见"的约束。

**G6 天气合规失败，`反驳` 出现**
→ planner 知道天气问题，但选择反驳坚持排露天景点，且最终未通过（有害反驳）。说明 planner 的天气感知 prompt 权重不够。

**评委均分低（< 3.5），代码全过**
→ 方案通过了硬性检查，但质量平庸（偏好不贴合 / 主题混乱 / 节奏不匹配）。优化 planner 的 prompt，或检查景点池质量。

---

## 新增用例的 Checklist

- [ ] `id` 唯一，与文件名一致（不含 `.json`）
- [ ] `tier` 选 `regression`（正常场景）或 `capability`（挑战场景）
- [ ] `pois` 每条有 `name / rating / location.lat / location.lng / open_time / indoor`
- [ ] `weather_forecast` 长度 = `days`，手工构造目标天气场景
- [ ] `is_bad: true` 的天 → `indoor: false` 的 POI 数量超过 `outdoor_on_bad_day_max` → 这才是负样本（否则太容易过）
- [ ] 跑 `--no-judge --k 1` 冒烟确认不报错
