# -*- coding: utf-8 -*-
"""
githubreport - わたしのGitHub活動レポート

GitHubユーザー名を入力すると、公開APIから取得した情報で活動レポートを表示する
単一ファイル Flask アプリ。DBは使わない。

目次
  1. 設定・定数
  2. GitHub API 取得（urllib、タイムアウト10秒、5分キャッシュ）
  3. 集計ロジック（総スター・言語別・上位/最近の抽出）
  4. エラー整形
  5. 画面（HTMLテンプレート）とルーティング
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from flask import Flask, render_template_string, request

# ============================
# 1. 設定・定数
# ============================

API_BASE = "https://api.github.com"
FETCH_TIMEOUT = 10  # 秒
CACHE_TTL = 300  # 秒（5分）
MAX_PAGES = 10  # リポジトリ取得の最大ページ数（per_page=100）

app = Flask(__name__)

# プロセス内キャッシュ: {username_lower: (取得時刻(monotonic), レポートdict)}
_cache: dict = {}


# ============================
# 2. GitHub API 取得
# ============================


def fetch_json(url: str):
    """GitHub API から JSON を取得する。GITHUB_TOKEN があれば認証に使う。"""
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "githubreport-app")
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_user(username: str) -> dict:
    return fetch_json(f"{API_BASE}/users/{username}")


def fetch_all_repos(username: str) -> list:
    """ユーザーの公開リポジトリを全件取得する（100件ずつページング）。"""
    repos: list = []
    for page in range(1, MAX_PAGES + 1):
        batch = fetch_json(
            f"{API_BASE}/users/{username}/repos?per_page=100&page={page}"
            "&sort=updated"
        )
        if not isinstance(batch, list):
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
    return repos


# ============================
# 3. 集計ロジック
# ============================


def summarize_repos(repos: list) -> dict:
    """リポジトリ一覧から総スター・言語別件数・上位/最近リストを作る。"""
    total_stars = 0
    lang_counts: dict = {}
    for repo in repos:
        total_stars += int(repo.get("stargazers_count") or 0)
        lang = repo.get("language") or "その他"
        lang_counts[lang] = lang_counts.get(lang, 0) + 1

    languages = sorted(lang_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    total_repos = len(repos)
    language_bars = [
        {
            "name": name,
            "count": count,
            "percent": round(count * 100 / total_repos, 1) if total_repos else 0,
        }
        for name, count in languages
    ]

    top_starred = sorted(
        repos, key=lambda r: (-(r.get("stargazers_count") or 0), r.get("name") or "")
    )[:5]
    recent = sorted(repos, key=lambda r: r.get("updated_at") or "", reverse=True)[:5]

    return {
        "total_stars": total_stars,
        "language_bars": language_bars,
        "top_starred": [
            {
                "name": r.get("name"),
                "stars": r.get("stargazers_count") or 0,
                "language": r.get("language") or "その他",
                "url": r.get("html_url"),
            }
            for r in top_starred
        ],
        "recent": [
            {
                "name": r.get("name"),
                "updated_at": format_date(r.get("updated_at")),
                "language": r.get("language") or "その他",
                "url": r.get("html_url"),
            }
            for r in recent
        ],
    }


def format_date(iso_text):
    """ISO8601文字列を YYYY-MM-DD 表記にする。変換できなければそのまま返す。"""
    if not iso_text:
        return "-"
    try:
        dt = datetime.strptime(iso_text, "%Y-%m-%dT%H:%M:%SZ")
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return str(iso_text)


def build_report(username: str) -> dict:
    """ユーザー情報＋リポジトリ集計をまとめたレポートdictを作る。"""
    user = fetch_user(username)
    repos = fetch_all_repos(username)
    summary = summarize_repos(repos)
    return {
        "login": user.get("login") or username,
        "name": user.get("name") or "",
        "avatar_url": user.get("avatar_url") or "",
        "profile_url": user.get("html_url") or f"https://github.com/{username}",
        "public_repos": user.get("public_repos"),
        "followers": user.get("followers"),
        "following": user.get("following"),
        "created_at": format_date(user.get("created_at")),
        "fetched_repos": len(repos),
        **summary,
    }


def get_report(username: str) -> dict:
    """5分キャッシュ付きでレポートを取得する。"""
    key = username.lower()
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    report = build_report(username)
    _cache[key] = (now, report)
    return report


# ============================
# 4. エラー整形
# ============================


def friendly_error(exc: Exception) -> str:
    """例外を利用者向けの分かりやすい日本語メッセージに変換する。"""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return "そのユーザー名のGitHubアカウントは見つかりませんでした。入力を確認してください。"
        if exc.code == 403:
            return "GitHub APIの利用制限に達した可能性があります。しばらく待ってから再度お試しください。"
        return f"GitHub APIからエラーが返りました（HTTP {exc.code}）。時間をおいて再度お試しください。"
    if isinstance(exc, urllib.error.URLError):
        return "GitHub APIへ接続できませんでした。ネットワーク状況を確認して再度お試しください。"
    if isinstance(exc, TimeoutError):
        return "GitHub APIへの接続がタイムアウトしました。再度お試しください。"
    return "予期しないエラーが発生しました。再度お試しください。"


# ============================
# 5. 画面とルーティング
# ============================

PAGE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>わたしのGitHub活動レポート</title>
<style>
  body { font-family: sans-serif; margin: 0; background: #f6f8fa; color: #24292f; }
  .wrap { max-width: 760px; margin: 0 auto; padding: 24px 16px 48px; }
  h1 { font-size: 22px; }
  form { display: flex; gap: 8px; margin: 16px 0; }
  input[type=text] { flex: 1; padding: 10px; font-size: 16px; border: 1px solid #d0d7de; border-radius: 6px; }
  button { padding: 10px 18px; font-size: 16px; border: 0; border-radius: 6px; background: #1f883d; color: #fff; cursor: pointer; }
  .card { background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
  .stats { display: flex; flex-wrap: wrap; gap: 12px; }
  .stat { flex: 1 1 140px; text-align: center; background: #f6f8fa; border-radius: 6px; padding: 12px 4px; }
  .stat .num { font-size: 24px; font-weight: bold; }
  .stat .label { font-size: 12px; color: #57606a; }
  .bar-row { display: flex; align-items: center; gap: 8px; margin: 6px 0; font-size: 14px; }
  .bar-name { width: 110px; text-align: right; }
  .bar-track { flex: 1; background: #eaeef2; border-radius: 4px; height: 14px; }
  .bar-fill { background: #0969da; height: 14px; border-radius: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  td, th { padding: 6px 4px; border-bottom: 1px solid #eaeef2; text-align: left; }
  .error { background: #ffebe9; border: 1px solid #ff8182; color: #82071e; border-radius: 6px; padding: 12px; }
  .note { font-size: 12px; color: #57606a; }
  img.avatar { width: 48px; height: 48px; border-radius: 50%; vertical-align: middle; }
</style>
</head>
<body>
<div class="wrap">
  <h1>📊 わたしのGitHub活動レポート</h1>
  <p>GitHubのユーザー名を入れると、公開情報から活動レポートを作ります。</p>
  <form method="get" action="/">
    <input type="text" name="user" placeholder="GitHubユーザー名（例: Arbeit2025）" value="{{ username or '' }}">
    <button type="submit">レポートを見る</button>
  </form>

  {% if error %}
    <div class="error">{{ error }}</div>
  {% endif %}

  {% if report %}
  <div class="card">
    <h2>
      {% if report.avatar_url %}<img class="avatar" src="{{ report.avatar_url }}" alt="">{% endif %}
      <a href="{{ report.profile_url }}">{{ report.login }}</a>{% if report.name %}（{{ report.name }}）{% endif %}
    </h2>
    <div class="stats">
      <div class="stat"><div class="num">{{ report.public_repos }}</div><div class="label">公開リポジトリ</div></div>
      <div class="stat"><div class="num">{{ report.total_stars }}</div><div class="label">総スター数</div></div>
      <div class="stat"><div class="num">{{ report.followers }}</div><div class="label">フォロワー</div></div>
      <div class="stat"><div class="num">{{ report.following }}</div><div class="label">フォロー中</div></div>
    </div>
    <p class="note">アカウント作成日: {{ report.created_at }} ／ 集計対象リポジトリ: {{ report.fetched_repos }}件</p>
  </div>

  <div class="card">
    <h3>言語別のリポジトリ数</h3>
    {% for lang in report.language_bars %}
    <div class="bar-row">
      <div class="bar-name">{{ lang.name }}</div>
      <div class="bar-track"><div class="bar-fill" style="width: {{ lang.percent }}%"></div></div>
      <div>{{ lang.count }}件（{{ lang.percent }}%）</div>
    </div>
    {% else %}
    <p>リポジトリがありません。</p>
    {% endfor %}
  </div>

  <div class="card">
    <h3>⭐ スター上位のリポジトリ</h3>
    <table>
      {% for r in report.top_starred %}
      <tr><td><a href="{{ r.url }}">{{ r.name }}</a></td><td>{{ r.language }}</td><td>★ {{ r.stars }}</td></tr>
      {% else %}
      <tr><td>リポジトリがありません。</td></tr>
      {% endfor %}
    </table>
  </div>

  <div class="card">
    <h3>🕘 最近更新したリポジトリ</h3>
    <table>
      {% for r in report.recent %}
      <tr><td><a href="{{ r.url }}">{{ r.name }}</a></td><td>{{ r.language }}</td><td>{{ r.updated_at }}</td></tr>
      {% else %}
      <tr><td>リポジトリがありません。</td></tr>
      {% endfor %}
    </table>
  </div>
  {% endif %}

  <p class="note">データはGitHub公開APIから取得しています（5分間キャッシュ）。</p>
</div>
</body>
</html>
"""


@app.route("/", methods=["GET"])
def index():
    username = (request.args.get("user") or "").strip()
    if not username:
        return render_template_string(PAGE, username="", report=None, error=None)
    try:
        report = get_report(username)
    except Exception as exc:  # noqa: BLE001 - 表示用に整形するため広く捕捉
        return render_template_string(
            PAGE, username=username, report=None, error=friendly_error(exc)
        )
    return render_template_string(PAGE, username=username, report=report, error=None)


@app.route("/healthz", methods=["GET"])
def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
