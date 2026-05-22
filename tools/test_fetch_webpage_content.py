import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_webpage_content as scraper


class CleanWebpageContentTests(unittest.TestCase):
    def test_html_to_clean_markdown_keeps_article_text_without_page_chrome(self) -> None:
        html = """
        <html>
          <body>
            <nav><a href="/hotel">酒店预订</a></nav>
            <main>
              <div>
                <a href="/flight">机票</a>
                <a href="/hotel">酒店</a>
                <a href="/train">火车票</a>
              </div>
              <article>
                <h1>常州武进一日游</h1>
                <p>
                  上午先去淹城遗址公园，看春秋时期的城池遗迹和博物馆展陈；
                  中午在湖塘找本地餐馆休息，下午安排西太湖散步，再根据天气选择
                  宝林禅寺或武进博物馆，整条路线适合不赶时间的一日游。出发前可以
                  先确认开馆时间，把室内场馆安排在午后最热的时段，再给晚饭留出
                  弹性时间；如果带孩子同行，景点之间优先选短距离接驳。
                </p>
                <p>
                  路线建议从地铁站附近起步，上午看遗址和展陈，中午补水休息，
                  下午把自然景观和人文场馆穿插起来。遇到雨天就先去博物馆，
                  晴天则把湖边步道放在傍晚，既能避开暴晒，也能保留拍照时间。
                </p>
                <a href="https://example.com/route">路线详情</a>
                <img src="route.jpg" alt="路线图">
                <aside class="advertisement">扫码领券广告</aside>
                <section>
                  <h2>更多推荐</h2>
                  <p>这段站内跳转推荐不应进入正文。</p>
                </section>
              </article>
            </main>
            <footer><a href="/about">关于我们</a></footer>
          </body>
        </html>
        """

        markdown = scraper.html_to_clean_markdown(html)

        self.assertIn("常州武进一日游", markdown)
        self.assertIn("路线详情", markdown)
        self.assertNotIn("酒店预订", markdown)
        self.assertNotIn("火车票", markdown)
        self.assertNotIn("扫码领券广告", markdown)
        self.assertNotIn("站内跳转推荐", markdown)
        self.assertNotIn("route.jpg", markdown)
        self.assertNotIn("https://example.com/route", markdown)
        self.assertNotIn("](", markdown)
        self.assertNotIn("![", markdown)

    def test_html_to_clean_markdown_rejects_shell_pages(self) -> None:
        html = """
        <html>
          <body>
            <div id="root"></div>
            <script>window.__BOOTSTRAP__ = {};</script>
            <p>打开 APP 查看</p>
          </body>
        </html>
        """

        markdown = scraper.html_to_clean_markdown(html)

        self.assertEqual("", markdown)

    def test_tavily_search_skips_results_without_meaningful_content(self) -> None:
        search_kwargs = {}
        search_calls = []

        class FakeClient:
            def search(self, *args, **kwargs):
                search_kwargs.update(kwargs)
                search_calls.append(kwargs.copy())
                return {
                    "results": [
                        {"title": "空壳页", "url": "https://empty.example"},
                        {"title": "正文页", "url": "https://guide.example"},
                    ]
                }

        full_content = "常州武进路线 " * 30
        progress = io.StringIO()
        with (
            patch.object(scraper, "get_tavily_client", return_value=FakeClient()),
            patch.object(
                scraper,
                "fetch_webpage_content",
                side_effect=["", full_content],
            ),
        ):
            markdown = scraper.tavily_search(
                "常州武进一日游攻略",
                max_results=1,
                search_timeout=12,
                fetch_timeout=3,
                progress_stream=progress,
            )

        self.assertNotIn("空壳页", markdown)
        self.assertNotIn("https://empty.example", markdown)
        self.assertIn("正文页", markdown)
        self.assertIn(full_content, markdown)
        self.assertEqual(12, search_kwargs["timeout"])
        self.assertEqual(
            list(scraper.PRIORITY_SEARCH_DOMAINS),
            search_calls[0]["include_domains"],
        )
        self.assertNotIn("include_domains", search_calls[1])
        self.assertIn("Searching Tavily", progress.getvalue())
        self.assertIn("Skipping candidate 1/2", progress.getvalue())
        self.assertIn("Accepted candidate 2/2", progress.getvalue())

    def test_tavily_search_fetches_priority_domain_before_fallback_results(self) -> None:
        class FakeClient:
            def search(self, *args, **kwargs):
                if kwargs.get("include_domains"):
                    return {
                        "results": [
                            {"title": "本地宝攻略", "url": "https://nj.bendibao.com/tour/route"},
                        ]
                    }
                return {
                    "results": [
                        {"title": "普通攻略", "url": "https://guide.example/route"},
                    ]
                }

        priority_content = "南京本地宝路线 " * 30
        with (
            patch.object(scraper, "get_tavily_client", return_value=FakeClient()),
            patch.object(
                scraper,
                "fetch_webpage_content",
                side_effect=[priority_content],
            ) as fetch_content,
        ):
            markdown = scraper.tavily_search("南京三日游攻略", max_results=1)

        self.assertIn("本地宝攻略", markdown)
        self.assertNotIn("普通攻略", markdown)
        fetch_content.assert_called_once_with(
            "https://nj.bendibao.com/tour/route",
            timeout=scraper.DEFAULT_FETCH_TIMEOUT,
        )


if __name__ == "__main__":
    unittest.main()
