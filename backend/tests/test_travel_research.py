import unittest

from backend.app.services import travel_research as research


class TravelResearchTests(unittest.TestCase):
    def test_html_to_clean_markdown_removes_page_chrome_and_keeps_article(self) -> None:
        html = """
        <html>
          <body>
            <header>顶部导航</header>
            <nav>首页 频道</nav>
            <article>
              <h1>南京三日游攻略</h1>
              <p>第一天可以去中山陵，中山陵适合历史文化偏好，可以安排较长的参观时间，慢慢看陵园建筑、林荫道和周边历史介绍。</p>
              <ul><li>然后去明孝陵，明孝陵周边绿意很足，适合和中山陵一起组成钟山风景区半日路线。</li><li>晚上去夫子庙，夫子庙适合看秦淮河夜景，也能补充城市历史街区体验。</li></ul>
              <p>这篇攻略重点保留真实景点名称和路线建议，方便后续模型抽取景点候选池，并统计景点在 markdown 中的实际出现次数。</p>
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
        html = "<html><body><main><p>太短了</p></main></body></html>"

        self.assertEqual("", research.html_to_clean_markdown(html))

    def test_rank_candidate_pool_counts_mentions_filters_hallucinations_and_sorts(self) -> None:
        pool = research.CandidatePool(
            candidate_pool=[
                research.AttractionCandidate(name="中山陵", preference_score=3),
                research.AttractionCandidate(name="明孝陵", preference_score=9),
                research.AttractionCandidate(name="夫子庙", preference_score=5),
                research.AttractionCandidate(name="不存在景点", preference_score=10),
                research.AttractionCandidate(name="明孝陵", preference_score=6),
            ]
        )
        markdown = "中山陵 中山陵 明孝陵 夫子庙 夫子庙"

        ranked = research.rank_candidate_pool(pool, markdown, max_candidates=10)

        self.assertEqual(
            [
                ("夫子庙", 2, 5),
                ("中山陵", 2, 3),
                ("明孝陵", 1, 9),
            ],
            [
                (item.name, item.mention_count, item.preference_score)
                for item in ranked.candidate_pool
            ],
        )

    def test_build_candidate_dicts_adds_builder_model_score_and_sources(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
