# LINE IT News Digest

主要IT系RSSフィード（ITmedia NEWS, GIGAZINE, Publickey, CNET Japan, Impress Watch, Zenn トレンド, Qiita 人気の投稿）を毎日取得し、
Gemini API（無料枠）に重要なニュースを選別・要約させて、LINEに自動配信する仕組みです。
GitHub Actions で毎日 08:00 JST に自動実行されます。

## 1. LINE Messaging API チャンネルを作成する

1. [LINE Developers Console](https://developers.line.biz/console/) に、普段使っているLINEアカウントでログインする
2. 「プロバイダー」を新規作成（まだなければ）
3. そのプロバイダー配下に「チャンネル」→「Messaging API」を新規作成
   - チャンネル名・説明・カテゴリ等は任意でよい
4. 作成したチャンネルの管理画面で以下を行う
   - 「Messaging API設定」タブ → 「チャンネルアクセストークン（長期）」を発行してコピーしておく
   - 同タブの「応答メッセージ」「あいさつメッセージ」はオフにしておくと通知が静かになる
   - QRコードまたは友だち追加用のLINE IDが表示されるので、**自分のLINEアプリでこのBotを友だち追加**する
     （配信は「友だち全員に送るbroadcast」方式なので、自分がbotの友だちになっていれば自分に届く）

これで必要なのは「チャンネルアクセストークン」の1つだけです。

## 2. Gemini APIキーを無料で発行する

1. [Google AI Studio](https://aistudio.google.com/apikey) に、普段使っているGoogleアカウントでログインする
2. "Create API key" でAPIキーを発行する（クレジットカード登録不要）
3. 無料枠（Free tier）にはリクエスト数のレート制限がありますが、1日1回ダイジェストを送るだけの用途なら十分です

> 無料枠で送信したデータはGoogleのモデル改善に利用される場合があります。気になる場合は有料プランに切り替えてください。

## 3. GitHubリポジトリを作成してこのフォルダをpushする

```bash
cd line-it-news
git init
git add .
git commit -m "Add LINE IT news digest bot"
gh repo create line-it-news --private --source=. --push
```

(`gh` が無い場合は GitHub上で空リポジトリを作り、`git remote add origin <URL>` して `git push` してください)

## 4. GitHub Secrets を設定する

リポジトリの Settings → Secrets and variables → Actions → "New repository secret" で以下を登録:

| Secret名 | 値 |
|---|---|
| `GEMINI_API_KEY` | Gemini APIキー |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINEチャンネルアクセストークン（長期） |

## 5. 動作確認

GitHubリポジトリの Actions タブ → "Daily IT News to LINE" → "Run workflow" で手動実行し、LINEに通知が来るか確認する。

成功すれば、以降は毎日 08:00 JST に自動実行されます。実行時刻を変えたい場合は
[.github/workflows/daily-news.yml](.github/workflows/daily-news.yml) の `cron` の値を変更してください（UTC指定）。

## ローカルで試す場合

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...
export LINE_CHANNEL_ACCESS_TOKEN=...
python main.py
```

## カスタマイズ

- `main.py` の `FEEDS` にRSSフィードを追加・削除できます
- `TOP_N`（配信件数、デフォルト6件）、`LOOKBACK_HOURS`（何時間以内の記事を対象にするか、デフォルト26時間）は環境変数で調整できます
