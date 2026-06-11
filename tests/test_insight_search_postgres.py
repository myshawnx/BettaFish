import unittest
from unittest.mock import patch

import InsightEngine.tools.search as search_module
from InsightEngine.tools.search import MediaCrawlerDB
from InsightEngine.utils.config import settings


class InsightSearchPostgresTestCase(unittest.TestCase):
    def test_platform_search_uses_postgres_named_params(self):
        db = MediaCrawlerDB()
        captured = []

        def fake_execute(query, params):
            captured.append((query, params))
            if '"weibo_note"' not in query:
                return []
            return [
                {
                    "id": 1,
                    "content": "低空物流试点需要同步公开夜间禁飞规则。",
                    "nickname": "城市观察员",
                    "note_url": "https://portfolio.example/weibo/910001",
                    "create_date_time": "2026-05-20 10:00:00",
                    "liked_count": "10",
                    "comments_count": "2",
                    "shared_count": "1",
                    "source_keyword": "低空物流",
                }
            ]

        with patch.object(settings, "DB_DIALECT", "postgresql"), patch.object(db, "_execute_query", fake_execute):
            response = db.search_topic_on_platform(
                platform="weibo",
                topic="低空物流",
                start_date="2026-05-20",
                end_date="2026-05-21",
                limit=5,
            )

        self.assertEqual(response.results_count, 1)
        first_query, first_params = captured[0]
        self.assertIn('"weibo_note"', first_query)
        self.assertIn('CAST("content" AS TEXT) ILIKE :platform_0_term_0', first_query)
        self.assertIn('"create_date_time" >= :platform_0_start', first_query)
        self.assertEqual(first_params["platform_0_term_0"], "%低空物流%")
        self.assertNotIn("%s", first_query)
        self.assertNotIn("UNSIGNED", first_query)
        self.assertNotIn("SHOW COLUMNS", first_query)

    def test_unavailable_database_returns_clear_empty_response(self):
        async def failing_fetch_all(query, params=None):
            raise OSError("[WinError 1225] 远程计算机拒绝网络连接。")

        db = MediaCrawlerDB()
        with patch.object(settings, "DB_DIALECT", "postgresql"), patch.object(search_module, "fetch_all", failing_fetch_all):
            response = db.search_topic_globally("低空物流", limit_per_table=1)

        self.assertEqual(response.results_count, 0)
        self.assertEqual(response.results, [])
        self.assertTrue(response.error_message)
        self.assertIn("空结果", response.error_message)
        self.assertFalse(db._database_available)

    def test_get_comments_uses_static_column_whitelist(self):
        db = MediaCrawlerDB()
        self.assertIn("comment_like_count", db._get_table_columns("weibo_note_comment"))
        self.assertEqual(db._get_table_columns("not_allowed"), [])


if __name__ == "__main__":
    unittest.main()
