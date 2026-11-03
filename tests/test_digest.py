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
