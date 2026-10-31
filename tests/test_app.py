# -*- coding: utf-8 -*-
"""githubreport の単体テスト。

実APIには依存せず、フィクスチャJSONと fetch_json の差し替えで検証する。
"""

import importlib.util
import os
import sys
import unittest
import urllib.error

APP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"
)


def load_app_module():
    spec = importlib.util.spec_from_file_location("githubreport_app", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


USER_FIXTURE = {
    "login": "someone",
    "name": "Some One",
    "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4",
    "html_url": "https://github.com/someone",
    "public_repos": 7,
    "followers": 42,
    "following": 13,
    "created_at": "2020-01-02T03:04:05Z",
}

REPOS_FIXTURE = [
    {"name": "alpha", "stargazers_count": 10, "language": "Python",
     "updated_at": "2026-10-01T00:00:00Z", "html_url": "https://github.com/someone/alpha"},
    {"name": "beta", "stargazers_count": 30, "language": "Python",
     "updated_at": "2026-10-20T00:00:00Z", "html_url": "https://github.com/someone/beta"},
    {"name": "gamma", "stargazers_count": 5, "language": "HTML",
     "updated_at": "2026-09-15T00:00:00Z", "html_url": "https://github.com/someone/gamma"},
    {"name": "delta", "stargazers_count": 30, "language": None,
     "updated_at": "2026-10-25T00:00:00Z", "html_url": "https://github.com/someone/delta"},
    {"name": "epsilon", "stargazers_count": 0, "language": "HTML",
     "updated_at": "2026-08-01T00:00:00Z", "html_url": "https://github.com/someone/epsilon"},
    {"name": "zeta", "stargazers_count": 3, "language": "CSS",
     "updated_at": "2026-10-10T00:00:00Z", "html_url": "https://github.com/someone/zeta"},
    {"name": "eta", "stargazers_count": 1, "language": "Python",
     "updated_at": "2026-07-01T00:00:00Z", "html_url": "https://github.com/someone/eta"},
]


class SummarizeTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_app_module()

    def test_total_stars(self):
        summary = self.mod.summarize_repos(REPOS_FIXTURE)
        self.assertEqual(summary["total_stars"], 79)

    def test_language_counts_sorted(self):
        summary = self.mod.summarize_repos(REPOS_FIXTURE)
        bars = summary["language_bars"]
        self.assertEqual(bars[0]["name"], "Python")
        self.assertEqual(bars[0]["count"], 3)
        counts = {b["name"]: b["count"] for b in bars}
        self.assertEqual(counts["HTML"], 2)
        self.assertEqual(counts["その他"], 1)  # language=None は「その他」
        self.assertAlmostEqual(bars[0]["percent"], 42.9, places=1)

    def test_top_starred_limit_and_order(self):
        summary = self.mod.summarize_repos(REPOS_FIXTURE)
        top = summary["top_starred"]
        self.assertEqual(len(top), 5)
        self.assertEqual(top[0]["stars"], 30)
        self.assertEqual(top[-1]["stars"], 3)
        names = [r["name"] for r in top]
        self.assertNotIn("epsilon", names)  # ★0 は上位5件に入らない
        self.assertNotIn("eta", names)

    def test_recent_order(self):
        summary = self.mod.summarize_repos(REPOS_FIXTURE)
        recent = summary["recent"]
        self.assertEqual(len(recent), 5)
        self.assertEqual(recent[0]["name"], "delta")  # 2026-10-25 が最新
        self.assertEqual(recent[0]["updated_at"], "2026-10-25")
        self.assertEqual(recent[-1]["name"], "gamma")

    def test_empty_repos(self):
        summary = self.mod.summarize_repos([])
        self.assertEqual(summary["total_stars"], 0)
        self.assertEqual(summary["language_bars"], [])
        self.assertEqual(summary["top_starred"], [])
        self.assertEqual(summary["recent"], [])

    def test_format_date(self):
        self.assertEqual(self.mod.format_date("2020-01-02T03:04:05Z"), "2020-01-02")
        self.assertEqual(self.mod.format_date(None), "-")
        self.assertEqual(self.mod.format_date("not-a-date"), "not-a-date")


class FriendlyErrorTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_app_module()

    def test_404_message(self):
        exc = urllib.error.HTTPError("https://api.github.com", 404, "Not Found", {}, None)
        msg = self.mod.friendly_error(exc)
        self.assertIn("見つかりませんでした", msg)

    def test_403_message(self):
        exc = urllib.error.HTTPError("https://api.github.com", 403, "Forbidden", {}, None)
        msg = self.mod.friendly_error(exc)
        self.assertIn("利用制限", msg)

    def test_url_error_message(self):
        exc = urllib.error.URLError("connection refused")
        msg = self.mod.friendly_error(exc)
        self.assertIn("接続できませんでした", msg)


class PageTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_app_module()
        self.mod._cache.clear()
        self.client = self.mod.app.test_client()

        def fake_fetch_json(url):
            if "/repos" in url:
                return REPOS_FIXTURE if "page=1" in url else []
            return USER_FIXTURE

        self.mod.fetch_json = fake_fetch_json

    def test_top_page_200(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("GitHub活動レポート", resp.get_data(as_text=True))

    def test_report_page_with_fixture(self):
        resp = self.client.get("/?user=someone")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("someone", body)
        self.assertIn("79", body)  # 総スター
        self.assertIn("2020-01-02", body)  # アカウント作成日
        self.assertIn("beta", body)  # スター上位
        self.assertIn("Python", body)  # 言語バー

    def test_report_404_error_display(self):
        def failing_fetch_json(url):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

        self.mod.fetch_json = failing_fetch_json
        resp = self.client.get("/?user=ghost-user")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("見つかりませんでした", resp.get_data(as_text=True))

    def test_healthz(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
