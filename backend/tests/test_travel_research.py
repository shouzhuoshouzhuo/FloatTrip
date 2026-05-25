"""网页调研与候选池抽取工具单元测试。

功能：
    验证 HTML 清噪、候选景点名称总出现次数统计、排序和候选字典构造行为。
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.services import travel_research as research


class TravelResearchTests(unittest.TestCase):
    """功能：覆盖旅行调研服务的纯函数行为。"""

    def test_html_to_clean_markdown_removes_page_chrome_and_keeps_article(self) -> None:
        """功能：验证 HTML 转 markdown 时会移除导航页脚并保留正文攻略。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证 markdown 内容。
        """
        html = """
        <html>
          <body>
            <header>顶部导航</header>
            <nav>首页 频道</nav>
            <article>
              <h1>南京三日游攻略</h1>
              <p>第一天可以去中山陵，中山陵适合历史文化偏好，可以安排较长的参观时间，慢慢看陵园建筑、林荫道和周边历史介绍。</p>
              <ul><li>然后去明孝陵，明孝陵周边绿意很足，适合和中山陵一起组成钟山风景区半日路线。</li><li>晚上去夫子庙，夫子庙适合看秦淮河夜景，也能补充城市历史街区体验。</li></ul>
              <p>这篇攻略重点保留真实景点名称和路线建议，方便后续模型抽取景点候选池，并统计景点名称在 markdown 中的总出现次数。</p>
              <p>如果用户偏好轻松节奏，可以把中山陵和明孝陵放在白天，把夫子庙放在傍晚以后；如果用户偏好历史文化，则可以增加南京博物院或总统府作为同城候选景点。</p>
              <div class="related"><a>推荐一</a><a>推荐二</a><a>推荐三</a></div>
            </article>
            <footer>Copyright 2026</footer>
            <script>console.log("noise")</script>
          </body>
        </html>
        """

        markdown = research.html_to_clean_markdown(html)

        self.assertIn("南京三日游攻略", markdown)
        self.assertIn("中山陵", markdown)
        self.assertIn("明孝陵", markdown)
        self.assertIn("夫子庙", markdown)
        self.assertNotIn("顶部导航", markdown)
        self.assertNotIn("推荐一", markdown)
        self.assertNotIn("Copyright", markdown)
        self.assertNotIn("console.log", markdown)

    def test_html_to_clean_markdown_returns_empty_for_short_content(self) -> None:
        """功能：验证正文过短页面会被判定为不可用内容。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证空字符串结果。
        """
        html = "<html><body><main><p>太短了</p></main></body></html>"

        self.assertEqual("", research.html_to_clean_markdown(html))

    def test_rank_candidate_pool_counts_total_name_mentions_and_sorts(self) -> None:
        """功能：验证候选池会统计名称总出现次数、过滤幻觉景点并按规则排序。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证排序结果。
        """
        pool = research.CandidatePool(
            candidate_pool=[
                research.AttractionCandidate(name="中山陵", preference_score=3),
                research.AttractionCandidate(name="明孝陵", preference_score=9),
                research.AttractionCandidate(name="夫子庙", preference_score=5),
                research.AttractionCandidate(name="不存在景点", preference_score=10),
                research.AttractionCandidate(name="明孝陵", preference_score=6),
            ]
        )
        markdown_documents = [
            "中山陵 中山陵 明孝陵 夫子庙 夫子庙",
            "夫子庙",
        ]

        ranked = research.rank_candidate_pool(pool, markdown_documents, max_candidates=10)

        self.assertEqual(
            [
                ("夫子庙", 3, 5),
                ("中山陵", 2, 3),
                ("明孝陵", 1, 9),
            ],
            [
                (item.name, item.mention_count, item.preference_score)
                for item in ranked.candidate_pool
            ],
        )

    def test_sort_candidates_node_rejects_empty_structured_candidate_pool(self) -> None:
        """功能：验证结构化候选池为空时返回明确错误而不是 AttributeError。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证错误提示。
        """
        with self.assertRaisesRegex(RuntimeError, "DeepSeek 未返回候选景点池"):
            research.sort_candidates_node(
                {
                    "candidate_pool": None,
                    "markdown_guides": "中山陵 夫子庙",
                    "markdown_documents": ["中山陵 夫子庙"],
                    "max_candidates": 8,
                }
            )

    def test_build_candidate_dicts_adds_builder_model_score_and_sources(self) -> None:
        """功能：验证候选字典会补充构建器、模型、分数和来源文档。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证候选字段。
        """
        pool = research.RankedCandidatePool(
            candidate_pool=[
                research.RankedAttractionCandidate(
                    name="中山陵",
                    preference_score=8,
                    mention_count=3,
                )
            ]
        )
        documents = [
            research.ResearchDocument(
                title="南京攻略",
                url="https://example.com/a",
                source="tavily",
                text="中山陵 明孝陵",
            ),
            research.ResearchDocument(
                title="无关攻略",
                url="https://example.com/b",
                source="tavily",
                text="夫子庙 老门东",
            ),
        ]

        candidates = research.build_candidate_dicts(pool, documents, "deepseek-v4-flash")

        self.assertEqual("中山陵", candidates[0]["name"])
        self.assertEqual(3, candidates[0]["mention_count"])
        self.assertEqual(8, candidates[0]["preference_score"])
        self.assertEqual(308, candidates[0]["score"])
        self.assertEqual("deepseek_markdown", candidates[0]["candidate_builder"])
        self.assertEqual("deepseek-v4-flash", candidates[0]["model"])
        self.assertEqual([{"title": "南京攻略", "url": "https://example.com/a", "source": "tavily"}], candidates[0]["sources"])

    def test_tavily_search_results_prioritizes_bendibao_and_ctrip_guides(self) -> None:
        """功能：验证 Tavily 优先搜索会同时覆盖本地宝和携程攻略。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证 Tavily 调用参数。
        """
        search_calls = []

        class FakeTavilyClient:
            """功能：记录 Tavily 搜索调用参数的测试替身。"""

            def __init__(self, api_key: str) -> None:
                """功能：接收 API Key 以模拟真实 TavilyClient 初始化。

                参数：
                    api_key：测试用 API Key。
                返回值：
                    无返回值。
                """
                self.api_key = api_key

            def search(self, *args, **kwargs):
                """功能：记录搜索参数并返回测试搜索结果。

                参数：
                    args：位置参数，包含搜索词。
                    kwargs：关键字参数，包含 include_domains 等搜索配置。
                返回值：
                    返回模拟 Tavily 搜索结果。
                """
                search_calls.append(kwargs.copy())
                title = "优先攻略" if kwargs.get("include_domains") else "普通攻略"
                url = "https://you.ctrip.com/sight/nanjing9.html" if kwargs.get("include_domains") else "https://guide.example/nanjing"
                return {"results": [{"title": title, "url": url, "content": "南京攻略"}]}

        fake_tavily = SimpleNamespace(TavilyClient=FakeTavilyClient)
        with (
            patch.dict("sys.modules", {"tavily": fake_tavily}),
            patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}),
        ):
            results = research.tavily_search_results("南京三日游攻略", max_results=8)

        self.assertEqual(list(research.PRIORITY_SEARCH_DOMAINS), search_calls[0]["include_domains"])
        self.assertEqual(["bendibao.com", "you.ctrip.com"], search_calls[0]["include_domains"])
        self.assertNotIn("include_domains", search_calls[1])
        self.assertEqual("https://you.ctrip.com/sight/nanjing9.html", results[0].url)

    def test_normalize_query_plan_guarantees_popular_attraction_queries(self) -> None:
        """功能：验证候选池搜索计划会保留热门景点宽泛搜索。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证 query 计划。
        """
        queries = research.normalize_query_plan(
            ["南京 三日游 攻略", "南京 三日游 攻略", "南京 小众历史文化景点"],
            "南京",
            3,
            ["历史文化"],
        )

        self.assertIn("南京 热门旅游景点", queries)
        self.assertIn("南京 必去景点 排行榜", queries)
        self.assertIn("南京 景点推荐 攻略", queries)
        self.assertIn("南京 历史文化 景点推荐", queries)
        self.assertIn("南京 三日游 攻略 景点", queries)
        self.assertEqual(len(queries), len(set(queries)))

    def test_plan_search_queries_node_merges_llm_queries_with_popular_fallback(self) -> None:
        """功能：验证搜索词规划节点会合并 LLM query 和热门景点兜底 query。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证节点输出。
        """

        class FakeQueryPlanner:
            """功能：模拟 DeepSeek 搜索词规划模型。"""

            def invoke(self, _messages):
                """功能：返回固定搜索词计划。

                参数：
                    _messages：调用方传入的对话消息，本测试中不使用。
                返回值：
                    返回 SearchQueryPlan。
                """
                return research.SearchQueryPlan(
                    queries=["南京 三日游 攻略", "南京 博物馆 景点推荐"]
                )

        node = research.plan_search_queries_node(FakeQueryPlanner())
        result = node({"destination": "南京", "days": 3, "preferences": ["博物馆"]})

        self.assertEqual("南京 热门旅游景点", result["query_plan"][0])
        self.assertIn("南京 博物馆 景点推荐", result["query_plan"])

    def test_search_markdown_research_tool_merges_multiple_rounds(self) -> None:
        """功能：验证 Agent 搜索工具会合并多轮真实搜索结果并按 URL 去重。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证合并结果。
        """
        existing_bundle = research.ResearchBundle(
            query_plan=["南京 热门旅游景点"],
            search_results=[
                research.SearchResult(
                    title="南京热门景点",
                    url="https://example.com/hot",
                    snippet="中山陵 夫子庙",
                    source="test",
                )
            ],
            documents=[
                research.ResearchDocument(
                    title="南京热门景点",
                    url="https://example.com/hot",
                    source="test",
                    text="中山陵 夫子庙",
                )
            ],
            warnings=[],
        )
        new_bundle = research.ResearchBundle(
            query_plan=["南京 必去景点"],
            search_results=[
                research.SearchResult(
                    title="重复页面",
                    url="https://example.com/hot",
                    snippet="中山陵",
                    source="test",
                ),
                research.SearchResult(
                    title="南京必去景点",
                    url="https://example.com/must",
                    snippet="明孝陵 南京博物院",
                    source="test",
                ),
            ],
            documents=[
                research.ResearchDocument(
                    title="重复页面",
                    url="https://example.com/hot",
                    source="test",
                    text="中山陵",
                ),
                research.ResearchDocument(
                    title="南京必去景点",
                    url="https://example.com/must",
                    source="test",
                    text="明孝陵 南京博物院",
                ),
            ],
            warnings=[],
        )

        with patch(
            "backend.app.services.travel_research.collect_research_for_queries",
            return_value=new_bundle,
        ):
            merged = research.search_markdown_research_tool(
                ["南京 必去景点"],
                existing_bundle=existing_bundle,
                max_results=8,
            )

        self.assertEqual(["南京 热门旅游景点", "南京 必去景点"], merged.query_plan)
        self.assertEqual(
            ["https://example.com/hot", "https://example.com/must"],
            [result.url for result in merged.search_results],
        )
        self.assertEqual(2, len(merged.documents))

    def test_candidate_pool_quality_check_requests_more_search_when_evidence_is_low(self) -> None:
        """功能：验证候选池数量或文档证据不足时 Agent 会继续搜索。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证质量判断。
        """
        state = {
            "days": 3,
            "max_candidates": 20,
            "search_iterations": 1,
            "markdown_documents": ["中山陵 夫子庙"],
            "research_bundle": research.ResearchBundle(
                query_plan=["南京 热门旅游景点"],
                search_results=[],
                documents=[],
                warnings=[],
            ),
            "ranked_candidate_pool": research.RankedCandidatePool(
                candidate_pool=[
                    research.RankedAttractionCandidate(
                        name="中山陵",
                        preference_score=8,
                        mention_count=1,
                    )
                ]
            ),
        }

        self.assertTrue(
            research.candidate_pool_needs_more_search(
                state,
                max_search_iterations=3,
                max_search_results=8,
            )
        )

    def test_candidate_pool_quality_check_continues_after_initial_search_budget(self) -> None:
        """功能：验证首轮搜索结果已满但候选仍少时 Agent 仍会继续补搜。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证质量判断。
        """
        state = {
            "days": 3,
            "max_candidates": 20,
            "search_iterations": 1,
            "markdown_documents": ["南京汤山一品温泉 汤山紫清湖旅游区森林温泉"],
            "research_bundle": research.ResearchBundle(
                query_plan=["南京 热门旅游景点"],
                search_results=[
                    research.SearchResult(
                        title=f"结果{index}",
                        url=f"https://example.com/{index}",
                        snippet="南京景点",
                        source="test",
                    )
                    for index in range(8)
                ],
                documents=[
                    research.ResearchDocument(
                        title="南京温泉",
                        url="https://example.com/hot-spring",
                        source="test",
                        text="南京汤山一品温泉 汤山紫清湖旅游区森林温泉",
                    )
                ],
                warnings=[],
            ),
            "ranked_candidate_pool": research.RankedCandidatePool(
                candidate_pool=[
                    research.RankedAttractionCandidate(
                        name="南京汤山一品温泉",
                        preference_score=5,
                        mention_count=1,
                    ),
                    research.RankedAttractionCandidate(
                        name="汤山紫清湖旅游区森林温泉",
                        preference_score=5,
                        mention_count=1,
                    ),
                ]
            ),
        }

        self.assertTrue(
            research.candidate_pool_needs_more_search(
                state,
                max_search_iterations=3,
                max_search_results=8,
            )
        )

    def test_collect_research_node_expands_search_budget_on_followup(self) -> None:
        """功能：验证补充搜索轮次会扩大搜索预算，避免被首轮 8 条结果卡住。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证传给搜索工具的 max_results。
        """
        bundle = research.ResearchBundle(
            query_plan=["南京 旅游景点排名"],
            search_results=[],
            documents=[
                research.ResearchDocument(
                    title="南京景点",
                    url="https://example.com/nanjing",
                    source="test",
                    text="中山陵 夫子庙 南京博物院",
                )
            ],
            warnings=[],
        )

        with patch(
            "backend.app.services.travel_research.search_markdown_research_tool",
            return_value=bundle,
        ) as search_tool:
            node = research.collect_research_node(
                per_query_limit=3,
                max_search_results=8,
                max_page_chars=12_000,
            )
            node(
                {
                    "pending_search_queries": ["南京 旅游景点排名"],
                    "search_iterations": 1,
                }
            )

        self.assertEqual(16, search_tool.call_args.kwargs["max_results"])

    def test_followup_query_plan_filters_existing_queries(self) -> None:
        """功能：验证补充 query 会避开已搜索词并保留新搜索方向。

        参数：
            无。
        返回值：
            无返回值；通过 unittest 断言验证补充 query。
        """
        queries = research.normalize_followup_query_plan(
            ["南京 热门旅游景点", "南京 旅游景点排名"],
            "南京",
            3,
            ["历史文化"],
            existing_queries=["南京 热门旅游景点"],
        )

        self.assertIn("南京 旅游景点排名", queries)
        self.assertNotIn("南京 热门旅游景点", queries)


if __name__ == "__main__":
    unittest.main()
