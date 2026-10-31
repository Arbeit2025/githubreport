# githubreport（わたしのGitHub活動レポート）

GitHubのユーザー名を入力すると、公開APIから取得した情報で、そのアカウントの活動レポートを表示する単一ファイル Flask アプリです。DBは使いません。

## できること

- 公開リポジトリ数、フォロワー数、フォロー数、アカウント作成日の表示
- 総スター数（自分のリポジトリについたスターの合計）
- 言語別のリポジトリ数（CSSバーで割合表示）
- スター上位5リポジトリ、最近更新した5リポジトリの一覧
- 存在しないユーザーやAPIエラー時は、日本語の分かりやすいエラー表示

## 仕組み

- データ取得はサーバー側で `urllib` を使い、タイムアウトは10秒です
- 取得結果はプロセス内に5分間キャッシュします
- 環境変数 `GITHUB_TOKEN` が設定されていれば、GitHub API の Authorization ヘッダーに使います（任意）。未設定でも公開情報の範囲で動作しますが、未認証のAPIには時間あたりの利用制限があります
- リポジトリは100件ずつページングして取得します（最大1000件まで）

## ローカルでの動かし方

```bash
pip install -r requirements.txt
python app.py
```

ブラウザで http://localhost:5000 を開き、ユーザー名を入力してください。

任意：APIの制限を緩和したい場合

```bash
export GITHUB_TOKEN=<your token>
```

## Render へのデプロイ

`render.yaml` を同梱しています（Web Service / Free プラン、起動コマンドは `gunicorn app:app`、ヘルスチェックは `/healthz`）。

## テスト

```bash
python -m unittest discover -s tests
```

実APIには依存せず、フィクスチャJSONで集計ロジックと画面表示を検証します。
