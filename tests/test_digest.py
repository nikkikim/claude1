import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import news_digest as nd

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>새 기사</title><link>https://ex.com/a?x=1</link>
<description>&lt;b&gt;본문&lt;/b&gt;</description><pubDate>Tue, 03 Nov 2026 01:00:00 GMT</pubDate></item>
<item><title>중복</title><link>https://ex.com/a?x=2</link><pubDate>Tue, 03 Nov 2026 01:00:00 GMT</pubDate></item>
<item><title>오래된 기사</title><link>https://ex.com/old</link><pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_fetch_filters_old_and_dupes(tmp_path):
    f = tmp_path / "f.xml"
    f.write_text(RSS, encoding="utf-8")
    cfg = {"feeds": [{"name": "T", "url": str(f)}], "max_age_hours": 26}
    now = datetime(2026, 11, 3, 3, 0, tzinfo=timezone.utc)
    arts = nd.fetch_articles(cfg, now=now)
    assert [a.title for a in arts] == ["새 기사"]
    assert arts[0].summary == "본문"


def test_parse_json_handles_fences():
    assert nd.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert nd.parse_json('설명 {"a": 1} 끝') == {"a": 1}


def test_render_escapes_html_and_unsafe_links():
    digest = {"headline": "<script>", "sections": [{"topic": "t", "items": [
        {"title": "<b>x</b>", "summary": "s", "source": "S", "link": "javascript:alert(1)"}]}]}
    out = nd.render_html(digest, datetime(2026, 11, 3))
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert "javascript:" not in out


def _big_digest(n=60):
    items = [{"title": f"제목{i} <&>", "summary": "요약 " * 40, "source": "S",
              "link": f"https://ex.com/{i}"} for i in range(n)]
    return {"headline": "h", "sections": [{"topic": "t", "items": items}]}


def test_telegram_messages_respect_limit_and_escape():
    msgs = nd.render_telegram(_big_digest(), datetime(2026, 11, 3))
    assert len(msgs) > 1
    assert all(len(m) <= 4096 for m in msgs)
    assert "&lt;&amp;&gt;" in msgs[0] and "<&>" not in msgs[0]


def test_telegram_unsafe_link_neutralised():
    d = {"headline": "h", "sections": [{"topic": "t", "items": [
        {"title": "x", "summary": "s", "source": "S", "link": "javascript:alert(1)"}]}]}
    assert "javascript:" not in nd.render_telegram(d, datetime(2026, 11, 3))[0]


def test_configured_channels(monkeypatch):
    for k in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    assert nd.configured_channels() == []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    assert nd.configured_channels() == ["telegram"]
    for k in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"):
        monkeypatch.setenv(k, "x")
    assert nd.configured_channels() == ["email", "telegram"]


def test_send_telegram_posts_to_each_chat(monkeypatch):
    sent = []

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(nd.urllib.request, "urlopen", lambda req, timeout=0: sent.append(req) or R())
    monkeypatch.setattr(nd.time, "sleep", lambda s: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1, 2")
    nd.send_telegram(["a", "b"])
    assert len(sent) == 4 and "botTOK/sendMessage" in sent[0].full_url


def _art(outlet, region, category):
    return nd.Article(outlet=outlet, region=region, category=category,
                      title="t", link="https://ex.com/" + outlet, summary="s", published=None)


def test_outlets_by_region_keeps_order_and_dedupes():
    arts = [_art("연합뉴스", "국내", "정치"), _art("BBC", "해외", "국제"),
            _art("연합뉴스", "국내", "경제"), _art("NYT", "해외", "국제")]
    assert nd.outlets_by_region(arts) == {"국내": ["연합뉴스"], "해외": ["BBC", "NYT"]}


def test_headlines_only_groups_by_category_in_fixed_order():
    arts = [_art("A", "국내", "경제"), _art("B", "국내", "정치"), _art("C", "해외", "기타")]
    topics = [s["topic"] for s in nd.headlines_only(arts)["sections"]]
    assert topics == ["정치", "경제", "기타"]


def test_render_html_lists_outlets():
    d = {"headline": "h", "sections": [], "outlets": {"국내": ["연합뉴스"], "해외": ["BBC", "NYT"]}}
    out = nd.render_html(d, datetime(2026, 11, 4))
    assert "참고한 신문사" in out and "BBC, NYT" in out and "2026년 11월 4일" in out
