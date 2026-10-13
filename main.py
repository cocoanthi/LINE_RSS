"""IT news digest: fetch RSS feeds, curate with Gemini, push to LINE."""
import os
import sys

# Must run before any Unicode is printed. GitHub Actions can default to ASCII.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from datetime import datetime, timedelta, timezone

import feedparser
import requests
from google import genai

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
HTTP_TIMEOUT = 20
USER_AGENT = "LINE-IT-News/1.0 (+https://github.com/cocoanthi/LINE_RSS)"


def _safe_print(*args, file=None, **kwargs):
    """Print Unicode even when stdout/stderr is stuck on ASCII."""
    target = sys.stderr if file is sys.stderr else (file or sys.stdout)
    try:
        print(*args, file=target, **kwargs)
        return
    except UnicodeEncodeError:
        pass
    sep = kwargs.get("sep", " ")
    end = kwargs.get("end", "\n")
    text = sep.join(str(a) for a in args) + end
    buf = getattr(target, "buffer", None)
    if buf is None:
        raise
    buf.write(text.encode("utf-8", errors="replace"))
    buf.flush()


def _ascii_secret(name):
    """HTTP headers (httpx/requests) require ASCII. Strip copy/paste junk."""
    raw = os.environ[name]
    cleaned = (
        raw.replace("\ufeff", "")
        .replace("\u200b", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
        .replace("\xa0", " ")
        .strip()
        .replace("\r", "")
        .replace("\n", "")
        .replace(" ", "")
    )
    bad = [i for i, ch in enumerate(cleaned) if not ch.isascii()]
    if bad:
        raise SystemExit(
            f"[ERROR] {name} has non-ASCII characters at positions {bad[:8]}. "
            "HTTP headers cannot contain them. Re-copy the secret from the console."
        )
    if not cleaned:
        raise SystemExit(f"[ERROR] {name} is empty")
    return cleaned


def fetch_recent_entries():
    cutoff = datetime.now(JST) - timedelta(hours=LOOKBACK_HOURS)
    entries = []
    for source_name, url in FEEDS:
        try:
            resp = requests.get(
                url,
                timeout=HTTP_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
        except Exception as e:
            _safe_print(f"[WARN] failed to fetch {source_name}: {e}", file=sys.stderr)
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


def curate_with_gemini(entries):
    if not entries:
        return None

    api_key = _ascii_secret("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

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

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text.strip()


def send_to_line(text):
    """Broadcasts to every friend of the LINE Official Account (bot).

    Using broadcast avoids needing to capture a specific userId via a
    webhook server; for personal use, just add your own bot as a friend.
    """
    token = _ascii_secret("LINE_CHANNEL_ACCESS_TOKEN")

    resp = requests.post(
        "https://api.line.me/v2/bot/message/broadcast",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        json={"messages": [{"type": "text", "text": text}]},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()


def main():
    _safe_print(
        f"[INFO] stdout={sys.stdout.encoding!r} stderr={sys.stderr.encoding!r}"
    )
    entries = fetch_recent_entries()
    _safe_print(f"[INFO] fetched {len(entries)} recent entries")

    digest = curate_with_gemini(entries)
    if not digest:
        _safe_print("[INFO] no news to send today, skipping")
        return

    _safe_print("---- digest ----")
    _safe_print(digest)
    _safe_print("----------------")

    send_to_line(digest)
    _safe_print("[INFO] sent to LINE")


if __name__ == "__main__":
    main()
