"""IT news digest: fetch RSS feeds, curate with Gemini, push to LINE."""
import os
import time
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
import requests
from google import genai
from google.genai import errors as genai_errors

JST = timezone(timedelta(hours=9))

FEEDS = [
    ("ITmedia NEWS", "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml"),
    ("GIGAZINE", "https://gigazine.net/news/rss_2.0/"),
    ("Publickey", "https://www.publickey1.jp/atom.xml"),
    ("CNET Japan", "https://feed.japan.cnet.com/rss/index.rdf"),
    ("Impress Watch", "https://www.watch.impress.co.jp/data/rss/1.0/ipw/feed.rdf"),
    ("Zenn トレンド", "https://zenn.dev/feed"),
    ("Qiita 人気の投稿", "https://qiita.com/popular-items/feed"),
]

LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "26"))
MAX_ITEMS_PER_FEED = 15
TOP_N = int(os.environ.get("TOP_N", "6"))
GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_RETRIES = 5
_RETRYABLE = (
    genai_errors.ServerError,
    httpx.TransportError,
    httpx.TimeoutException,
)


def fetch_recent_entries():
    cutoff = datetime.now(JST) - timedelta(hours=LOOKBACK_HOURS)
    entries = []
    for source_name, url in FEEDS:
        try:
            parsed = feedparser.parse(url)
        except Exception:
            continue
        for entry in parsed.entries[:MAX_ITEMS_PER_FEED]:
            published = _entry_time(entry)
            if published is not None and published < cutoff:
                continue
            entries.append(
                {
                    "source": source_name,
                    "title": entry.get("title", "").strip(),
                    "link": entry.get("link", "").strip(),
                    "summary": _strip_html(entry.get("summary", ""))[:500],
                }
            )
    return entries


def _entry_time(entry):
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc).astimezone(JST)
    return None


def _strip_html(text):
    import re

    return re.sub(r"<[^>]+>", "", text or "").strip()


def _retryable(exc):
    if isinstance(exc, _RETRYABLE):
        return True
    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    return isinstance(cause, _RETRYABLE)


def curate_with_gemini(entries):
    if not entries:
        return None

    listing = "\n".join(
        f"{i+1}. [{e['source']}] {e['title']} — {e['link']}\n   概要: {e['summary']}"
        for i, e in enumerate(entries)
    )

    prompt = f"""以下はIT関連ニュースの候補一覧です。この中から、日本のITエンジニア・IT業界関係者にとって
重要度・関心度が高いニュースを最大{TOP_N}件選び、LINEで配信するためのテキストを作成してください。

候補一覧:
{listing}

出力ルール:
- 件数は多くても{TOP_N}件まで。ニュースが少ない場合は無理に{TOP_N}件に揃えなくてよい
- 重複する話題は1件にまとめる
- 各ニュースは「タイトル（1行）→ 1〜2文の要約 → リンク」の形式
- 先頭に「📱 今日のIT関連ニュース（YYYY/MM/DD）」のような日付入り見出しを付ける（日付は日本時間の今日の日付）
- LINEのトーク画面でそのまま読める、絵文字を軽く使ったプレーンテキストにする（Markdown記法は使わない）
- 全体で1500文字以内に収める
- ニュース本文以外の前置き・後書き・注釈は出力しない"""

    last_error = None
    for attempt in range(GEMINI_RETRIES):
        try:
            # Recreate the client: a dropped HTTP/2 connection is not reusable.
            client = genai.Client(api_key=_secret("GEMINI_API_KEY"))
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            return response.text.strip()
        except Exception as e:
            last_error = e
            if not _retryable(e) or attempt == GEMINI_RETRIES - 1:
                raise
            time.sleep(2 ** (attempt + 2))
    raise last_error


def _secret(name):
    raw = os.environ[name]
    cleaned = (
        raw.replace("\ufeff", "")
        .replace("\u200b", "")
        .strip()
        .replace("\r", "")
        .replace("\n", "")
        .strip()
    )
    if cleaned.lower().startswith("bearer "):
        cleaned = cleaned[7:].strip()
    return cleaned


def send_to_line(text):
    """Broadcasts to every friend of the LINE Official Account (bot).

    Using broadcast avoids needing to capture a specific userId via a
    webhook server; for personal use, just add your own bot as a friend.
    """
    token = _secret("LINE_CHANNEL_ACCESS_TOKEN")

    resp = requests.post(
        "https://api.line.me/v2/bot/message/broadcast",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        json={"messages": [{"type": "text", "text": text}]},
        timeout=20,
    )
    if resp.status_code == 401:
        raise SystemExit(
            "LINE returned 401 Unauthorized. Update GitHub secret "
            "LINE_CHANNEL_ACCESS_TOKEN with a new long-lived channel access "
            "token from LINE Developers Console > Messaging API."
        )
    resp.raise_for_status()


def main():
    entries = fetch_recent_entries()
    digest = curate_with_gemini(entries)
    if not digest:
        return
    send_to_line(digest)


if __name__ == "__main__":
    main()
