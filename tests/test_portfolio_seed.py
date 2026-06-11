import json
import unittest
from pathlib import Path

from scripts.seed_portfolio_data import (
    DEFAULT_DATA_PATH,
    IDENTITY_COLUMNS,
    INSERT_ORDER,
    count_seed_rows,
    load_seed_data,
    seed_portfolio_data,
)


class PortfolioSeedTestCase(unittest.TestCase):
    def test_seed_file_has_deterministic_portfolio_shape(self):
        data = load_seed_data(DEFAULT_DATA_PATH)
        self.assertEqual(data["version"], 1)
        self.assertGreaterEqual(count_seed_rows(data), 20)
        self.assertLessEqual(count_seed_rows(data), 50)

        tables = data["tables"]
        self.assertTrue(set(INSERT_ORDER).issubset(tables))
        self.assertEqual(len(tables["daily_topics"]), 3)
        self.assertEqual(
            {row["topic_id"] for row in tables["daily_topics"]},
            {
                "portfolio_low_altitude_logistics",
                "portfolio_ai_health_assistant",
                "portfolio_ev_service",
            },
        )

        for table_name, identity in IDENTITY_COLUMNS.items():
            for row in tables[table_name]:
                if isinstance(identity, tuple):
                    self.assertTrue(all(column in row for column in identity))
                else:
                    self.assertIn(identity, row)

    def test_seed_file_uses_fixed_dates_and_portfolio_ids(self):
        raw = json.loads(Path(DEFAULT_DATA_PATH).read_text(encoding="utf-8"))
        rows = [row for table_rows in raw["tables"].values() for row in table_rows]

        date_values = {
            value
            for row in rows
            for key, value in row.items()
            if key.endswith("_date") or key in {"create_date_time", "publish_time"}
        }
        self.assertTrue(any(str(value).startswith("2026-05-20") for value in date_values))
        self.assertTrue(any(str(value).startswith("2026-05-21") for value in date_values))
        self.assertTrue(any(str(value).startswith("2026-05-22") for value in date_values))

        ids = [
            str(value)
            for row in rows
            for key, value in row.items()
            if key.endswith("_id") or key == "task_id"
        ]
        self.assertTrue(any(value.startswith("portfolio_") for value in ids))

    def test_dry_run_validates_seed_file_without_database(self):
        result = seed_portfolio_data(dry_run=True)

        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["inserted"], 0)
        self.assertEqual(result["total_seed_rows"], count_seed_rows(load_seed_data(DEFAULT_DATA_PATH)))


if __name__ == "__main__":
    unittest.main()
