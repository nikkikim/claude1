import json
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


def test_pick_provider(monkeypatch):
    for k in ("LLM_PROVIDER", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert nd.pick_provider() == "none"
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert nd.pick_provider() == "gemini"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    assert nd.pick_provider() == "anthropic"
    monkeypatch.setenv("LLM_PROVIDER", "none")
    assert nd.pick_provider() == "none"


def test_gemini_call_sends_key_in_header_and_parses(monkeypatch):
    import io
    seen = {}
    body = {"candidates": [{"content": {"parts": [{"text": '{"headline": "h", "sections": []}'}]}}]}

    class _Resp:
        def __enter__(self):
            return io.StringIO(json.dumps(body))

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=0):
        seen["req"] = req
        return _Resp()

    monkeypatch.setattr(nd.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("GEMINI_API_KEY", "SECRETKEY")
    monkeypatch.setenv("GEMINI_MODEL", "m1")
    out = nd.summarize([_art("A", "국내", "정치")], "gemini")
    assert out == {"headline": "h", "sections": []}
    req = seen["req"]
    assert "SECRETKEY" not in req.full_url and "m1:generateContent" in req.full_url
    assert req.get_header("X-goog-api-key") == "SECRETKEY"


def test_main_falls_back_to_headlines_when_llm_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(nd, "fetch_articles", lambda cfg: [_art("A", "국내", "정치")])
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def boom(*a, **k):
        raise RuntimeError("quota")
    monkeypatch.setattr(nd, "summarize", boom)
    assert nd.main(["--dry-run"]) == 0
    assert "헤드라인만" in (tmp_path / "digest.html").read_text(encoding="utf-8")
    assert "요약 실패" in capsys.readouterr().err


def test_fetch_caps_total_and_interleaves(tmp_path):
    def feed(name, n):
        items = "".join(f"<item><title>{name}{i}</title><link>https://ex.com/{name}{i}</link>"
                        f"<pubDate>Tue, 03 Nov 2026 01:00:00 GMT</pubDate></item>" for i in range(n))
        f = tmp_path / f"{name}.xml"
        f.write_text(f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{items}</channel></rss>',
                     encoding="utf-8")
        return {"outlet": name, "region": "국내", "category": "정치", "url": str(f)}
    cfg = {"feeds": [feed("A", 5), feed("B", 5)], "max_items_per_feed": 5,
           "max_total_articles": 4, "max_age_hours": 26}
    arts = nd.fetch_articles(cfg, now=datetime(2026, 11, 3, 3, 0, tzinfo=timezone.utc))
    assert [a.outlet for a in arts] == ["A", "B", "A", "B"]


def _gh_env(monkeypatch, **extra):
    for k in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
              "ISSUE_NOTIFY", "ISSUE_ASSIGNEES"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "TOK")
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/news")
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "me")
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def test_github_channel_auto_when_no_other_channel(monkeypatch):
    _gh_env(monkeypatch)
    assert nd.configured_channels() == ["github"]
    monkeypatch.setenv("ISSUE_NOTIFY", "false")
    assert nd.configured_channels() == []


def test_github_channel_not_auto_when_email_set_unless_forced(monkeypatch):
    _gh_env(monkeypatch, SMTP_USER="a", SMTP_PASSWORD="b", MAIL_TO="c")
    assert nd.configured_channels() == ["email"]
    monkeypatch.setenv("ISSUE_NOTIFY", "true")
    assert nd.configured_channels() == ["email", "github"]


def test_github_channel_off_outside_actions(monkeypatch):
    _gh_env(monkeypatch)
    monkeypatch.delenv("GITHUB_ACTIONS")
    assert nd.configured_channels() == []


def test_render_markdown_neutralises_mentions_and_markup():
    d = {"headline": "@elon says *hi*", "sections": [{"topic": "정치", "items": [
        {"title": "[x](http://evil) @bob #1", "summary": "<img src=x> a_b", "source": "S",
         "link": "https://ex.com/a(b)"}]}], "outlets": {"국내": ["연합뉴스"]}}
    md = nd.render_markdown(d, datetime(2026, 11, 4))
    assert "@bob" not in md and "@elon" not in md          # 멘션 무력화
    assert "[x](http://evil)" not in md                    # 제목 속 링크 문법 무력화
    assert "\\<img" in md and "\n<img" not in md and " <img" not in md   # < 앞에 \가 붙어 글자로만 표시됨
    assert "https://ex.com/a(b%29" in md                   # URL 속 ')' 가 링크를 깨지 않게 인코딩됨
    assert "참고한 신문사" in md and "### 정치" in md


def test_send_github_issue_payload_and_retry_without_assignee(monkeypatch):
    import io
    import urllib.error
    calls = []

    def fake_urlopen(req, timeout=0):
        payload = json.loads(req.data)
        calls.append(payload)
        if "assignees" in payload:
            raise urllib.error.HTTPError(req.full_url, 422, "bad", {}, io.BytesIO(b"invalid assignee"))

        class R:
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return R()

    _gh_env(monkeypatch)
    monkeypatch.setattr(nd.urllib.request, "urlopen", fake_urlopen)
    nd.send_github_issue("제목", "본문")
    assert calls[0]["assignees"] == ["me"] and calls[0]["title"] == "제목"
    assert "assignees" not in calls[1]          # 422 → 담당자 없이 재시도


def _ov_digest():
    return {"headline": "h", "sections": [
        {"topic": "정치", "overview": "정치 <핵심> & 요약", "items": [
            {"title": "t1", "summary": "s1", "source": "S", "link": "https://ex.com/1"}]},
        {"topic": "경제", "items": [
            {"title": "t2", "summary": "s2", "source": "S", "link": "https://ex.com/2"}]},  # overview 없음
    ]}


def test_overview_block_is_at_top_in_every_format():
    d, day = _ov_digest(), datetime(2026, 11, 4)
    h = nd.render_html(d, day)
    assert "카테고리별 오늘의 핵심" in h and h.index("카테고리별 오늘의 핵심") < h.index("<h2")
    assert "정치 &lt;핵심&gt; &amp; 요약" in h and "<핵심>" not in h        # HTML 이스케이프
    t = nd.render_text(d)
    assert t.index("[카테고리별 오늘의 핵심]") < t.index("■ 정치")
    tg = nd.render_telegram(d, day)[0]
    assert tg.index("카테고리별 오늘의 핵심") < tg.index("■ 정치") and "&lt;핵심&gt;" in tg
    md = nd.render_markdown(d, day)
    assert md.index("카테고리별 오늘의 핵심") < md.index("### 정치") and "\\<핵심\\>" in md
    assert "경제 ·" not in t and "**경제** ·" not in md                      # overview 없는 카테고리는 생략


def test_no_overview_block_in_headlines_mode():
    d = nd.headlines_only([_art("A", "국내", "정치")])
    assert "카테고리별 오늘의 핵심" not in nd.render_html(d, datetime(2026, 11, 4))
    assert "카테고리별 오늘의 핵심" not in nd.render_markdown(d, datetime(2026, 11, 4))


def test_prompt_requires_overview_in_schema():
    assert '"overview"' in nd.SYSTEM_PROMPT and "overview를 반드시" in nd.SYSTEM_PROMPT


def _http_error(code, body):
    import io
    import urllib.error
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body.encode()))


def _gemini_failing(monkeypatch, code, body):
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(1)
        raise _http_error(code, body)

    monkeypatch.setattr(nd.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(nd.time, "sleep", lambda s: None)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    return calls


def test_gemini_daily_quota_is_not_retried(monkeypatch):
    import pytest
    calls = _gemini_failing(monkeypatch, 429,
                            '{"error": {"message": "quota", "details": ["GenerateRequestsPerDayPerProjectPerModel-FreeTier"]}}')
    with pytest.raises(nd.QuotaExceeded):
        nd._call_gemini("s", "u")
    assert len(calls) == 1                     # 하루 한도는 기다려도 소용없으므로 즉시 포기


def test_gemini_minute_quota_is_retried_then_quota_error(monkeypatch):
    import pytest
    calls = _gemini_failing(monkeypatch, 429, '{"error": {"message": "Resource exhausted per minute"}}')
    with pytest.raises(nd.QuotaExceeded):
        nd._call_gemini("s", "u")
    assert len(calls) == 3                     # 분당 한도는 잠시 후 재시도


def test_gemini_free_tier_unavailable_is_detected(monkeypatch):
    import pytest
    _gemini_failing(monkeypatch, 403, '{"error": {"message": "The Gemini API free tier is not available for this project."}}')
    with pytest.raises(nd.FreeTierUnavailable):
        nd._call_gemini("s", "u")


def test_gemini_other_403_is_generic_error(monkeypatch):
    import pytest
    _gemini_failing(monkeypatch, 403, '{"error": {"message": "API key not valid"}}')
    with pytest.raises(RuntimeError) as ei:
        nd._call_gemini("s", "u")
    assert not isinstance(ei.value, (nd.QuotaExceeded, nd.FreeTierUnavailable))


def test_quota_exceeded_today_then_summary_returns_when_quota_refills(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(nd, "fetch_articles", lambda cfg: [_art("A", "국내", "정치")])
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    for k in ("LLM_PROVIDER", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)

    # 1일차: 한도 초과 → 헤드라인만 + 이유 표시, 그래도 정상 종료(메일은 발송됨)
    def over(*a, **k):
        raise nd.QuotaExceeded("429")
    monkeypatch.setattr(nd, "summarize", over)
    assert nd.main(["--dry-run"]) == 0
    day1 = (tmp_path / "digest.html").read_text(encoding="utf-8")
    assert "무료 사용 한도를 초과" in day1 and "카테고리별 오늘의 핵심" not in day1

    # 2일차: 한도가 다시 채워짐 → 별도 조치 없이 요약(핵심 블록 포함)이 돌아온다
    good = {"headline": "정상 요약", "sections": [{"topic": "정치", "overview": "핵심 흐름", "items": [
        {"title": "t", "summary": "s", "source": "A", "link": "https://ex.com/1"}]}]}
    monkeypatch.setattr(nd, "summarize", lambda articles, provider: good)
    assert nd.main(["--dry-run"]) == 0
    day2 = (tmp_path / "digest.html").read_text(encoding="utf-8")
    assert "정상 요약" in day2 and "카테고리별 오늘의 핵심" in day2 and "한도를 초과" not in day2


def test_free_tier_unavailable_note_in_digest(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(nd, "fetch_articles", lambda cfg: [_art("A", "국내", "정치")])
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    def nofree(*a, **k):
        raise nd.FreeTierUnavailable("403")
    monkeypatch.setattr(nd, "summarize", nofree)
    assert nd.main(["--dry-run"]) == 0
    assert "무료 티어를 쓸 수 없어" in (tmp_path / "digest.html").read_text(encoding="utf-8")
