#!/usr/bin/env python3
"""매일 주요 뉴스를 수집 → Claude로 요약 → 이메일 / 텔레그램 발송.

사용법:
    python news_digest.py              # 설정된 채널(이메일/텔레그램)로 모두 발송
    python news_digest.py --dry-run    # 발송 대신 digest.html 파일로 저장
    python news_digest.py --no-llm     # Claude 호출 없이 헤드라인만 (테스트용)

환경변수:
    ANTHROPIC_API_KEY   Claude API 키
    CLAUDE_MODEL        기본 claude-sonnet-5-5

  [이메일] 아래가 모두 있으면 이메일 발송
    SMTP_HOST / SMTP_PORT  (기본 smtp.gmail.com / 465)
    SMTP_USER / SMTP_PASSWORD  SMTP 계정 (Gmail은 앱 비밀번호)
    MAIL_TO             수신자 (쉼표로 여러 명)
    MAIL_FROM           발신자 (기본 SMTP_USER)

  [텔레그램] 아래가 모두 있으면 텔레그램 발송
    TELEGRAM_BOT_TOKEN  @BotFather에서 받은 봇 토큰
    TELEGRAM_CHAT_ID    받을 채팅 ID (쉼표로 여러 개 가능)
"""
from __future__ import annotations

import argparse
import calendar
import html
import json
import os
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import feedparser

KST = timezone(timedelta(hours=9))
CONFIG_PATH = Path(__file__).with_name("feeds.json")


@dataclass
class Article:
    source: str
    title: str
    link: str
    summary: str
    published: datetime | None


# ---------- 수집 ----------

def _entry_time(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)


def fetch_articles(config: dict, now: datetime | None = None) -> list[Article]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=config.get("max_age_hours", 26))
    per_feed = config.get("max_items_per_feed", 15)
    seen: set[str] = set()
    articles: list[Article] = []

    for feed in config["feeds"]:
        try:
            parsed = feedparser.parse(feed["url"], agent="news-digest/1.0")
        except Exception as e:  # 한 피드가 죽어도 전체는 계속
            print(f"[warn] {feed['name']}: {e}", file=sys.stderr)
            continue
        if parsed.get("bozo") and not parsed.entries:
            print(f"[warn] {feed['name']}: 피드를 읽지 못했습니다", file=sys.stderr)
            continue
        count = 0
        for entry in parsed.entries:
            title = (entry.get("title") or "").strip()
            link = entry.get("link") or ""
            if not title or not link:
                continue
            published = _entry_time(entry)
            if published and published < cutoff:
                continue
            key = link.split("?")[0]
            if key in seen or title in seen:
                continue
            seen.update({key, title})
            articles.append(Article(
                source=feed["name"],
                title=title,
                link=link,
                summary=_strip_html(entry.get("summary", ""))[:400],
                published=published,
            ))
            count += 1
            if count >= per_feed:
                break
    return articles


def _strip_html(text: str) -> str:
    import re
    return html.unescape(re.sub(r"<[^>]+>", " ", text)).strip()


# ---------- 요약 ----------

SYSTEM_PROMPT = """당신은 바쁜 독자를 위한 뉴스 에디터입니다.
주어진 기사 목록에서 오늘 가장 중요한 뉴스를 골라 한국어로 요약하세요.

규칙:
- 같은 사건을 다룬 기사는 하나로 묶고, 가장 대표적인 기사 링크를 사용하세요.
- 주제별로 분류하세요 (예: 정치, 경제, 국제, 사회, IT/과학, 문화 등 — 필요한 것만).
- 전체 8~15개 항목, 각 항목은 1~2문장. 사실 위주로, 과장·추측 금지.
- 기사 목록에 없는 내용은 절대 만들어내지 마세요.
- 해외 기사는 한국어로 번역해 요약하세요.
- 반드시 아래 JSON만 출력하세요 (설명, 코드펜스 없이):
{"headline": "오늘의 한 줄 요약", "sections": [{"topic": "주제", "items": [{"title": "제목", "summary": "요약", "source": "언론사", "link": "URL"}]}]}"""


def summarize(articles: list[Article], model: str) -> dict:
    import anthropic

    lines = [
        f"[{i}] ({a.source}) {a.title} | {a.summary} | {a.link}"
        for i, a in enumerate(articles, 1)
    ]
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "\n".join(lines)}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    return parse_json(text)


def parse_json(text: str) -> dict:
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"JSON을 찾을 수 없습니다: {text[:200]}")
    return json.loads(text[start:end + 1])


def headlines_only(articles: list[Article]) -> dict:
    """LLM 없이 소스별 헤드라인만 묶는 폴백."""
    by_source: dict[str, list[dict]] = {}
    for a in articles:
        by_source.setdefault(a.source, []).append(
            {"title": a.title, "summary": a.summary[:120], "source": a.source, "link": a.link}
        )
    return {
        "headline": "요약 없이 헤드라인만 제공합니다",
        "sections": [{"topic": s, "items": items[:5]} for s, items in by_source.items()],
    }


# ---------- 렌더링 ----------

def _safe_url(url: str) -> str:
    return url if url.startswith(("http://", "https://")) else "#"


def render_html(digest: dict, date: datetime) -> str:
    e = html.escape
    parts = [
        '<div style="max-width:640px;margin:0 auto;font-family:-apple-system,'
        "'Apple SD Gothic Neo','Malgun Gothic',sans-serif;color:#222;line-height:1.6\">",
        f'<h1 style="font-size:20px;margin:0 0 4px">📰 {date:%Y년 %m월 %d일} 뉴스 브리핑</h1>',
        f'<p style="margin:0 0 20px;color:#555">{e(digest.get("headline", ""))}</p>',
    ]
    for sec in digest.get("sections", []):
        parts.append(
            f'<h2 style="font-size:16px;border-bottom:2px solid #222;padding-bottom:4px;'
            f'margin:24px 0 8px">{e(sec.get("topic", ""))}</h2>'
        )
        for it in sec.get("items", []):
            parts.append(
                '<div style="margin:0 0 14px">'
                f'<a href="{e(_safe_url(it.get("link", "")))}" style="color:#0b57d0;'
                f'font-weight:600;text-decoration:none">{e(it.get("title", ""))}</a>'
                f'<div style="font-size:14px">{e(it.get("summary", ""))}</div>'
                f'<div style="font-size:12px;color:#888">{e(it.get("source", ""))}</div>'
                "</div>"
            )
    parts.append(
        '<p style="font-size:11px;color:#aaa;margin-top:32px">'
        "AI가 자동 요약한 내용이므로 중요한 사항은 원문을 확인하세요.</p></div>"
    )
    return "".join(parts)


def render_text(digest: dict) -> str:
    out = [digest.get("headline", ""), ""]
    for sec in digest.get("sections", []):
        out.append(f"■ {sec.get('topic', '')}")
        for it in sec.get("items", []):
            out.append(f"- {it.get('title', '')}\n  {it.get('summary', '')}\n  {it.get('link', '')}")
        out.append("")
    return "\n".join(out)


# ---------- 발송 ----------

def send_email(subject: str, html_body: str, text_body: str) -> None:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    to = [x.strip() for x in os.environ["MAIL_TO"].split(",") if x.strip()]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("MAIL_FROM", user)
    msg["To"] = ", ".join(to)
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port) as s:
            s.starttls(context=ctx)
            s.login(user, password)
            s.send_message(msg)


TELEGRAM_LIMIT = 4000  # API 한도는 4096자, 여유를 둠


def render_telegram(digest: dict, date: datetime) -> list[str]:
    """텔레그램 HTML 형식(<b>, <a>만 지원) 메시지 목록. 4096자 한도에 맞춰 분할."""
    e = html.escape
    blocks = [f"📰 <b>{date:%Y년 %m월 %d일} 뉴스 브리핑</b>\n{e(digest.get('headline', ''))}"]
    for sec in digest.get("sections", []):
        blocks.append(f"\n<b>■ {e(sec.get('topic', ''))}</b>")
        for it in sec.get("items", []):
            link = _safe_url(it.get("link", ""))
            blocks.append(
                f'• <a href="{e(link)}">{e(it.get("title", ""))}</a>\n'
                f'{e(it.get("summary", ""))} <i>({e(it.get("source", ""))})</i>'
            )
    messages: list[str] = []
    cur = ""
    for b in blocks:
        b = b[:TELEGRAM_LIMIT]
        if cur and len(cur) + len(b) + 2 > TELEGRAM_LIMIT:
            messages.append(cur)
            cur = b
        else:
            cur = f"{cur}\n\n{b}" if cur else b
    if cur:
        messages.append(cur)
    return messages


def send_telegram(messages: list[str]) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_ids = [x.strip() for x in os.environ["TELEGRAM_CHAT_ID"].split(",") if x.strip()]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chat_id in chat_ids:
        for text in messages:
            data = urllib.parse.urlencode({
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            }).encode()
            try:
                with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30):
                    pass
            except urllib.error.HTTPError as err:
                # 토큰이 URL에 들어 있으므로 예외 메시지를 그대로 노출하지 않음
                detail = err.read().decode("utf-8", "replace")[:300]
                raise RuntimeError(f"텔레그램 전송 실패 (HTTP {err.code}): {detail}") from None
            time.sleep(0.5)  # 연속 전송 제한 회피


def configured_channels() -> list[str]:
    channels = []
    if all(os.environ.get(k) for k in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO")):
        channels.append("email")
    if all(os.environ.get(k) for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")):
        channels.append("telegram")
    return channels


# ---------- main ----------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="발송 대신 digest.html로 저장")
    ap.add_argument("--no-llm", action="store_true", help="Claude 없이 헤드라인만")
    ap.add_argument("--config", default=str(CONFIG_PATH))
    args = ap.parse_args(argv)

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    articles = fetch_articles(config)
    print(f"수집된 기사: {len(articles)}건")
    if not articles:
        print("기사가 없어 발송하지 않습니다.", file=sys.stderr)
        return 1

    if args.no_llm:
        digest = headlines_only(articles)
    else:
        model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
        digest = summarize(articles, model)

    now = datetime.now(KST)
    html_body = render_html(digest, now)
    text_body = render_text(digest)
    subject = f"[뉴스 브리핑] {now:%m/%d} {digest.get('headline', '')}"[:120]

    if args.dry_run:
        Path("digest.html").write_text(html_body, encoding="utf-8")
        print("digest.html 저장 완료 (발송하지 않음)")
        for i, m in enumerate(render_telegram(digest, now), 1):
            print(f"--- 텔레그램 메시지 {i} ({len(m)}자) ---\n{m}")
        return 0

    channels = configured_channels()
    if not channels:
        print("발송 채널이 설정되지 않았습니다. 이메일(SMTP_*, MAIL_TO) 또는 "
              "텔레그램(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) 환경변수를 설정하세요.",
              file=sys.stderr)
        return 2

    failed = False
    for ch in channels:  # 한 채널이 실패해도 나머지는 계속 시도
        try:
            if ch == "email":
                send_email(subject, html_body, text_body)
            else:
                send_telegram(render_telegram(digest, now))
            print(f"발송 완료: {ch}")
        except Exception as err:
            failed = True
            print(f"[error] {ch} 발송 실패: {err}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
