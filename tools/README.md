# FloatTrip Tools 使用说明

本目录是一组旅行信息搜集、候选景点池生成、POI 过滤的小工具。所有脚本都会自动读取项目根目录的 `.env.local`。

## 环境变量

在项目根目录创建或更新 `.env.local`：

```bash
SEARCHAPI_API_KEY=
AMAP_API_KEY=
TAVILY_API_KEY=
BAIDU_APPBUILDER_API_KEY=
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash
BAIDU_AI_SEARCH_MODEL=ernie-4.5-turbo-32k
```

说明：

- `SEARCHAPI_API_KEY`：用于 `place_candidate_pool.py`，通过 SearchAPI 的 Baidu 引擎搜索。
- `AMAP_API_KEY`：用于 `amap_poi_filter.py`，通过高德 POI 校验真实景点。
- `TAVILY_API_KEY`：用于 `tavily_travel_research.py`。
- `BAIDU_APPBUILDER_API_KEY`：用于 `baidu_web_search_raw.py` 的百度非 AI 搜索，以及 `baidu_ai_search_travel_research.py` 的百度 AI 搜索。
- `DEEPSEEK_API_KEY`：用于 `llm_candidate_pool.py` 把搜索语料结构化为候选池。
- `DEEPSEEK_MODEL`：可选，默认 `deepseek-v4-flash`。
- `BAIDU_AI_SEARCH_MODEL`：可选，默认 `ernie-4.5-turbo-32k`。

## 推荐流程

### 百度非 AI 搜索 + LLM 候选池（推荐解耦流程）

```bash
python3 tools/baidu_web_search_raw.py 常州 --days 3 --travel-queries --top-k 10 --corpus-json > /tmp/search_corpus.json
python3 tools/llm_candidate_pool.py /tmp/search_corpus.json --names
```

输出为降序景点名，每行一个。

如需完整结构：

```bash
python3 tools/llm_candidate_pool.py /tmp/search_corpus.json --json
```

### 百度候选池再接高德真实 POI 过滤

```bash
python3 tools/llm_candidate_pool.py /tmp/search_corpus.json --json > /tmp/baidu_candidates.json
python3 tools/amap_poi_filter.py /tmp/baidu_candidates.json --names
```

### Tavily 搜索候选池

```bash
python3 tools/tavily_travel_research.py 常州 --days 3 --names
```

### Markdown 攻略 + LangGraph 结构化候选池

```bash
python3 tools/langgraph_markdown_candidate_pool.py tools/tavily_search_results.md --preferences 历史文化,亲子
```

输出 JSON 中每个候选景点包含 `name`、在 markdown 攻略中由代码统计的 `mention_count`，以及 LLM 给出的用户偏好 `preference_score`。

### SearchAPI/Baidu 规则候选池

```bash
python3 tools/place_candidate_pool.py 常州 --days 3 --json > /tmp/candidates.json
python3 tools/amap_poi_filter.py /tmp/candidates.json --names
```

### 高德真实 POI 再接区域聚类调试地图

高德过滤后的 `candidate_pool` 已包含 POI 坐标，可按旅行天数聚成区域候选簇，再生成调试地图观察分布：

```bash
python3 tools/amap_poi_filter.py /tmp/candidates.json --json > /tmp/amap_candidates.json
python3 tools/render_geo_day_clusters_map.py /tmp/amap_candidates.json --days 3 --output /tmp/geo_clusters.html
```

地图上的彩色点参与本轮聚类；灰点是按 `score` 优先、`mention_count` 回退排序后落在 `days * 4` 截断窗口外的候选。

## `baidu_web_search_raw.py`

用途：调用百度 AppBuilder 非 AI 网页搜索接口 `/v2/ai_search/web_search`，直接输出原始 JSON，方便观察 `references` 的原始结构。不做候选池、LLM 总结、去重或排序。

常用命令：

```bash
python3 tools/baidu_web_search_raw.py "北京有哪些旅游景区" --json
python3 tools/baidu_web_search_raw.py 常州 --days 3 --travel-queries --top-k 10 --json
python3 tools/baidu_web_search_raw.py 常州 --days 3 --travel-queries --top-k 10 --corpus-json
```

参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `query` | 必填 | 搜索词；开启 `--travel-queries` 时表示目的地，例如 `常州` |
| `--travel-queries` | 关闭 | 使用 FloatTrip 旅行搜索词批量查询 |
| `--days` | `3` | 旅行天数，仅 `--travel-queries` 时使用 |
| `--preferences` | 空 | 偏好，逗号分隔，仅 `--travel-queries` 时使用 |
| `--top-k` | `10` | 网页搜索返回条数，最大 50 |
| `--edition` | `standard` | 搜索版本，可选 `standard`、`lite` |
| `--timeout` | `30` | 单次请求超时秒数 |
| `--retries` | `1` | 失败重试次数 |
| `--json` | 开启/关闭均为 JSON | 保留该参数便于命令语义清晰，脚本默认输出 pretty JSON |
| `--corpus-json` | 关闭 | 输出统一 `SearchCorpus` JSON，供 `llm_candidate_pool.py` 使用 |

批量模式输出为数组，每项包含 `query` 和 `response`；失败项包含 `error`。

## `llm_candidate_pool.py`

用途：读取统一 `SearchCorpus` JSON，把 `documents[].content` 作为主输入交给 LLM 生成候选景点池。搜索模块和 LLM 模块互相解耦，后续增加搜索源只需要继续输出同一种 `SearchCorpus`。

常用命令：

```bash
python3 tools/llm_candidate_pool.py /tmp/search_corpus.json --names
python3 tools/llm_candidate_pool.py /tmp/search_corpus.json --json
python3 tools/llm_candidate_pool.py /tmp/search_corpus.json --names-json
```

参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `search_corpus_json` | 必填 | `SearchCorpus` JSON 文件路径 |
| `--model` | `DEEPSEEK_MODEL` 或 `deepseek-v4-flash` | DeepSeek 模型 |
| `--content-chars` | `1800` | 每篇搜索文档送入 LLM 的最大字符数 |
| `--timeout` | `90` | LLM 请求超时秒数 |
| `--json` | 关闭 | 输出完整候选池 JSON |
| `--names-json` | 关闭 | 只输出景点名称 JSON 数组 |
| `--names` | 关闭 | 只按降序逐行输出景点名称 |

输入 `SearchCorpus` 核心字段：

```json
{
  "schema_version": "search_corpus.v1",
  "destination": "常州",
  "days": 3,
  "preferences": [],
  "queries": ["常州 三日游 攻略 景点"],
  "providers": ["baidu_web_search"],
  "documents": [
    {
      "document_id": "baidu_web_search:1:xxxx",
      "provider": "baidu_web_search",
      "query": "常州 三日游 攻略 景点",
      "title": "来源标题",
      "url": "来源 URL",
      "site_name": "来源站点",
      "published_at": "发布时间",
      "content": "给 LLM 的主文本",
      "snippet": "短摘要或兜底文本",
      "rank": 1,
      "scores": {},
      "raw": {}
    }
  ],
  "raw_responses": []
}
```

## `langgraph_markdown_candidate_pool.py`

用途：读取 markdown 攻略文本，用 LangGraph 编排 DeepSeek strict function-calling `with_structured_output` 识别景点名和用户偏好分，再由代码统计景点名在 markdown 中的出现频率并降序输出。需要安装 `langgraph`、`langchain-openai` 和 `pydantic`。

常用命令：

```bash
python3 tools/langgraph_markdown_candidate_pool.py tools/tavily_search_results.md --preferences 历史文化,亲子
python3 tools/langgraph_markdown_candidate_pool.py /tmp/guides.md --model deepseekv4flash --max-candidates 30
```

参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `markdown_file` | 必填 | 包含攻略正文的 markdown 文件 |
| `--preferences` | 空 | 用户偏好，逗号分隔 |
| `--model` | `DEEPSEEK_MODEL` 或 `deepseek-v4-flash` | DeepSeek 结构化模型 |
| `--max-candidates` | `40` | 最多保留多少个候选景点 |
| `--max-markdown-chars` | `60000` | 最多送入 LLM 的 markdown 字符数 |

## `baidu_ai_search_travel_research.py`

用途：调用百度 AppBuilder AI 搜索收集网页引用，再把搜索结果交给 DeepSeek 结构化输出候选景点池。

常用命令：

```bash
python3 tools/baidu_ai_search_travel_research.py 常州 --days 3 --names
python3 tools/baidu_ai_search_travel_research.py 常州 --days 3 --json
python3 tools/baidu_ai_search_travel_research.py 常州 --days 3 --names-json
```

参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `destination` | 必填 | 目的地，例如 `常州` |
| `--days` | `3` | 旅行天数 |
| `--preferences` | 空 | 偏好，逗号分隔，例如 `亲子,博物馆` |
| `--top-k` | `10` | 每个搜索词最多取几条百度网页引用 |
| `--deep-search` | 关闭 | 开启百度深度搜索，成本和耗时更高 |
| `--max-workers` | `4` | 并行百度搜索 worker 数 |
| `--baidu-timeout` | `60` | 单个百度搜索请求超时秒数 |
| `--baidu-model` | `BAIDU_AI_SEARCH_MODEL` 或 `ernie-4.5-turbo-32k` | 百度 AI 搜索总结模型 |
| `--deepseek-model` | `DEEPSEEK_MODEL` 或 `deepseek-v4-flash` | DeepSeek 结构化模型 |
| `--json` | 关闭 | 输出完整 JSON |
| `--names-json` | 关闭 | 只输出景点名称 JSON 数组 |
| `--names` | 关闭 | 只按降序逐行输出景点名称 |

注意：

- 百度搜索阶段是并行调用，进度日志输出到 `stderr`。
- `--names` 的景点名输出在 `stdout`，适合管道处理。
- 如果百度接口很慢，可以降低 `--baidu-timeout` 或减少 `--max-workers`。

## `tavily_travel_research.py`

用途：调用 Tavily 搜集旅行攻略信息，并用规则抽取生成候选景点池。

常用命令：

```bash
python3 tools/tavily_travel_research.py 南京 --days 3 --preferences 历史文化,美食 --json
python3 tools/tavily_travel_research.py 南京 --days 3 --names
python3 tools/tavily_travel_research.py 南京 --days 3 --names-json
```

参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `destination` | 必填 | 目的地，例如 `南京` |
| `--days` | `3` | 旅行天数 |
| `--preferences` | 空 | 偏好，逗号分隔 |
| `--max-results` | `5` | 每个搜索词最多取几条 Tavily 结果 |
| `--search-depth` | `basic` | Tavily 搜索深度，可选 `basic`、`advanced`、`fast`、`ultra-fast` |
| `--include-answer` | 关闭 | 让 Tavily 返回查询摘要 answer |
| `--json` | 关闭 | 输出完整 JSON |
| `--names-json` | 关闭 | 只输出景点名称 JSON 数组 |
| `--names` | 关闭 | 只按降序逐行输出景点名称 |

## `place_candidate_pool.py`

用途：通过 SearchAPI 的 Baidu 引擎搜索，再用规则抽取生成候选景点池。

常用命令：

```bash
python3 tools/place_candidate_pool.py 南京 --days 3 --preferences 历史文化,美食 --json
python3 tools/place_candidate_pool.py 成都 --days 4
```

参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `destination` | 必填 | 目的地，例如 `南京` |
| `--days` | `3` | 旅行天数 |
| `--preferences` | 空 | 偏好，逗号分隔 |
| `--per-query-limit` | `10` | 每个搜索词最多取几条 SearchAPI/Baidu 结果 |
| `--json` | 关闭 | 输出完整 JSON |

## `amap_poi_filter.py`

用途：读取候选池 JSON，调用高德 POI 搜索，只保留真实景点类 POI。

常用命令：

```bash
python3 tools/amap_poi_filter.py /tmp/candidates.json --json
python3 tools/amap_poi_filter.py /tmp/candidates.json --admin-region 320402 --json
python3 tools/amap_poi_filter.py /tmp/candidates.json --names
python3 tools/amap_poi_filter.py /tmp/candidates.json --names-json
```

参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `candidate_json` | 必填 | 候选池 JSON 文件路径 |
| `--admin-region` | `--city` 或输入 JSON 的 `destination` | 需要匹配的高德行政区名称或 adcode；区县校验优先传 adcode |
| `--city` | 输入 JSON 的 `destination` | 兼容旧调用的行政区参数 |
| `--offset` | `5` | 每个候选名最多取几个高德 POI |
| `--min-mentions` | `1` | 最小出现次数，低于该次数会先过滤，不调用高德 |
| `--json` | 关闭 | 输出完整 JSON |
| `--names-json` | 关闭 | 只输出过滤后的景点名称 JSON 数组 |
| `--names` | 关闭 | 只按降序逐行输出过滤后的景点名称 |

## `geo_day_cluster.py`

用途：读取 `amap_poi_filter.py` 已补齐坐标的候选项，在后续选点和交通矩阵排序之前先按地理区域聚类。输出是区域候选簇，不是 Day 1、Day 2 这样的最终日程。

聚类函数要求每个候选包含 `mention_count` 和 `poi.location.lng` / `poi.location.lat`。第一版内部按 `score` 优先、`mention_count` 回退排序，只让前 `days * 4` 个候选进入加权 K-Medoids；聚类权重使用对数压缩后的 `mention_count`。

```python
from tools.geo_day_cluster import cluster_candidates_by_days

clusters = cluster_candidates_by_days(amap_payload["candidate_pool"], days=3)
for cluster in clusters:
    print(cluster["cluster_id"], cluster["medoid"]["name"], cluster["radius_km"])
```

## `render_geo_day_clusters_map.py`

用途：读取高德过滤后的完整候选池 JSON，调用区域聚类函数，输出 Leaflet HTML 调试地图。Leaflet 资源和地图瓦片由浏览器联网加载。

常用命令：

```bash
python3 tools/render_geo_day_clusters_map.py /tmp/amap_candidates.json --days 3 --output /tmp/geo_clusters.html
```

参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `input_json` | 必填 | `amap_poi_filter.py --json` 输出文件 |
| `--days` | 必填 | 旅行天数，也是区域聚类簇数 |
| `--output` | 必填 | 输出 HTML 文件路径 |
| `--min-cluster-size` | `2` | 每个区域簇的最少候选数 |
| `--max-iterations` | `50` | K-Medoids 最大迭代轮数 |

## 输出格式

完整 JSON 通常包含：

```json
{
  "destination": "常州",
  "days": 3,
  "preferences": [],
  "provider": "baidu_ai_search",
  "search_results": [],
  "candidate_pool": [
    {
      "name": "中华恐龙园",
      "mention_count": 3,
      "score": 3,
      "sources": []
    }
  ]
}
```

纯名称输出：

```text
中华恐龙园
天宁寺
青果巷
```

## 常见问题

### 命令看起来卡住

百度 AI 搜索和 LLM 结构化都可能较慢。百度脚本会把进度写到 `stderr`：

```bash
python3 tools/baidu_ai_search_travel_research.py 常州 --days 3 --names
```

如果仍然太慢，可以试：

```bash
python3 tools/baidu_ai_search_travel_research.py 常州 --days 3 --names --baidu-timeout 20 --max-workers 2
```

### 只想要最终真实景点

把搜索候选池接到高德过滤：

```bash
python3 tools/baidu_ai_search_travel_research.py 常州 --days 3 --json > /tmp/candidates.json
python3 tools/amap_poi_filter.py /tmp/candidates.json --names
```

### `--names` 有日志

日志在 `stderr`，景点名称在 `stdout`。如果要保存纯景点名：

```bash
python3 tools/baidu_ai_search_travel_research.py 常州 --days 3 --names > /tmp/place_names.txt
```
