import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import langgraph_markdown_candidate_pool as candidate_pool


class LangGraphMarkdownCandidatePoolTests(unittest.TestCase):
    def test_choose_http_proxy_ignores_socks_all_proxy(self) -> None:
        with patch.dict(
            candidate_pool.os.environ,
            {
                "ALL_PROXY": "socks5://127.0.0.1:7890",
                "HTTPS_PROXY": "http://127.0.0.1:7890",
            },
            clear=True,
        ):
            proxy = candidate_pool.choose_http_proxy()

        self.assertEqual("http://127.0.0.1:7890", proxy)

    def test_rank_candidate_pool_counts_markdown_mentions_before_sorting(self) -> None:
        pool = candidate_pool.CandidatePool(
            candidate_pool=[
                candidate_pool.AttractionCandidate(
                    name="偏好更高但提及较少",
                    preference_score=10,
                ),
                candidate_pool.AttractionCandidate(
                    name="高频景点",
                    preference_score=3,
                ),
                candidate_pool.AttractionCandidate(
                    name="同频更匹配",
                    preference_score=8,
                ),
                candidate_pool.AttractionCandidate(
                    name=" 同频更匹配 ",
                    preference_score=7,
                ),
                candidate_pool.AttractionCandidate(
                    name="零命中景点",
                    preference_score=9,
                ),
            ]
        )
        markdown = """
        高频景点适合上午游玩，高频景点临近地铁，高频景点夜景也好。
        同频更匹配适合亲子，同频更匹配可以慢慢逛，同频更匹配有展览。
        偏好更高但提及较少只在这里出现一次。
        """

        sorted_pool = candidate_pool.rank_candidate_pool(pool, markdown, max_candidates=3)

        self.assertEqual(
            ["同频更匹配", "高频景点", "偏好更高但提及较少"],
            [candidate.name for candidate in sorted_pool.candidate_pool],
        )
        self.assertEqual(
            [3, 3, 1],
            [candidate.mention_count for candidate in sorted_pool.candidate_pool],
        )


if __name__ == "__main__":
    unittest.main()
