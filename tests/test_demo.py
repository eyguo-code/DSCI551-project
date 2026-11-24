import os
import unittest
from datetime import date
from pathlib import Path

from movielens.dataset import read_dataset


ROOT = Path(__file__).resolve().parents[1]


class DatasetTest(unittest.TestCase):
    def test_archive_produces_normalized_tables_and_utc_timestamps(self):
        data = read_dataset(ROOT / "ml-latest-small.zip")
        self.assertEqual(
            {name: len(rows) for name, rows in data.items()},
            {"movies": 9742, "users": 610, "genres": 19, "movie_genres": 22050,
             "ratings": 100836, "tags": 3683},
        )
        self.assertEqual(sum(year is None for _, _, year in data["movies"]), 13)
        self.assertEqual(sum(genre == "IMAX" for _, genre in data["genres"]), 1)
        self.assertEqual(min(row[3] for row in data["ratings"]).isoformat(), "1996-03-29T18:36:55")


@unittest.skipUnless(os.getenv("MOVIELENS_TEST_MYSQL") == "1", "requires the seeded MySQL demo")
class MySQLDemoTest(unittest.TestCase):
    def test_queries_use_the_snapshot_and_keep_movies_without_tags(self):
        from movielens import queries as q
        from movielens.db import connect

        with connect() as db:
            self.assertEqual(q.overview(db)["ratings"], 100836)
            has_tags = q.search(db, "Toy Story (1995)", "Animation")
            self.assertIn("fun", has_tags[0]["tags"])
            self.assertTrue(any(row["tags"] is None for row in q.search(db, "a", "Drama")))
            self.assertEqual(q.search(db, "%", "Animation"), [])
            self.assertEqual(q.rankings(db, 20)[0]["rating_count"], 20)
            self.assertEqual(q.rankings(db, 20, "Drama", 1990, 1999)[0]["title"], "Shawshank Redemption, The (1994)")
            plan = q.ranking_plan(db, 20, "Drama", 1990, 1999)
            self.assertIn("actual time", plan)
            self.assertIn("join", plan)
            self.assertEqual(len(q.genre_stats(db)), 19)
            self.assertEqual(q.active_users(db)[0]["rating_count"], 2698)
            window = (date(2017, 1, 1), date(2017, 1, 8))
            self.assertEqual(q.rating_count(db, *window), 13)
            rows = q.rating_activity(db, *window)
            self.assertEqual(len(rows), 13)
            self.assertEqual(rows[0]["rated_at"].isoformat(), "2017-01-01T15:26:08")

    def test_index_comparison_forces_candidate_and_keeps_baseline(self):
        from movielens.db import connect
        from movielens.experiment import compare

        with connect() as db:
            result = compare(db, date(2017, 1, 1), date(2017, 1, 8), repeats=2)
            self.assertEqual(result["matched"], 13)
            self.assertIn("Table scan", result["baseline"]["plan"])
            self.assertIn("idx_ratings_rated_at", result["candidate"]["plan"])
            self.assertGreater(result["baseline"]["median_ms"], 0)

            wide = compare(db, date(2000, 1, 1), date(2018, 1, 1), repeats=1)
            self.assertEqual(wide["matched"], 83516)
            self.assertIn("Table scan", wide["baseline"]["plan"])
            self.assertIn("Index range scan", wide["candidate"]["plan"])
            self.assertTrue(wide["candidate"]["used_timestamp_index"])
            with db.cursor() as cursor:
                cursor.execute("SELECT @@SESSION.optimizer_switch AS switches")
                self.assertIn("use_invisible_indexes=off", cursor.fetchone()["switches"])

    def test_demo_views_and_live_index_button(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.metric[1].value, "100,836")
        self.assertFalse(app.dataframe[0].value.empty)
        for page in ("Rankings", "Rating activity", "Index lab"):
            app.radio(key="section").set_value(page).run()
            self.assertFalse(app.exception, page)
            self.assertFalse(app.error, page)
        app.button(key="run_index").click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.metric[4].value, "13")
        self.assertIn("idx_ratings_rated_at", app.code[-1].value)
