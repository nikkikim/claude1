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
    arts = [_art("A", "국내", "정치·사회"), _art("B", "국내", "세계 이슈"), _art("C", "해외", "기타")]
    topics = [s["topic"] for s in nd.headlines_only(arts)["sections"]]
    assert topics == ["세계 이슈", "정치·사회", "기타"]


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


def _a(outlet, region, category, title, summary=""):
    return nd.Article(outlet=outlet, region=region, category=category, title=title,
                      link=f"https://ex.com/{outlet}/{abs(hash(title))}", summary=summary, published=None)


def _titles(digest, topic):
    return [it["title"] for sec in digest["sections"] if sec["topic"] == topic for it in sec["items"]]


def test_focus_categories_come_first_with_art_prioritised():
    assert nd.CATEGORIES[:4] == ["세계 이슈", "경제·증시", "코인", "문화예술"]
    assert nd.CATEGORY_LIMITS["문화예술"] >= nd.CATEGORY_LIMITS["정치·사회"]


def test_art_headlines_drop_gossip_and_reserve_domestic_slots():
    arts = [_a("ARTnews", "미국", "문화예술", f"Museum exhibition of painter {i}") for i in range(6)]
    arts += [_a("Hyperallergic", "미국", "문화예술", f"Gallery auction curator {i}") for i in range(6)]
    arts += [_a("뉴시스", "국내", "문화예술", "서울시립미술관 기획전 개막")]
    arts += [_a("매일경제", "국내", "문화예술", "한국 현대미술 50년 전시")]
    arts += [_a("연합뉴스", "국내", "문화예술", "리센느 신곡 멜론 1위 직행")]   # 연예 가십
    titles = _titles(nd.headlines_only(arts), "문화예술")
    assert "서울시립미술관 기획전 개막" in titles and "한국 현대미술 50년 전시" in titles   # 국내 슬롯 확보
    assert "리센느 신곡 멜론 1위 직행" not in titles                                      # 가십 제외
    assert len(titles) <= nd.CATEGORY_LIMITS["문화예술"]
    assert sum(t.startswith("Museum") for t in titles) <= 3                              # 한 매체 독식 방지


def test_economy_headlines_keep_market_news_and_drop_unrelated():
    arts = [_a("연합뉴스", "국내", "경제·증시", "스마트팩토리 설비 확대"),
            _a("한국경제", "국내", "경제·증시", "코스피 급락…환율 1400원 돌파"),
            _a("Bloomberg", "미국", "경제·증시", "Stocks slide as Fed signals higher rates")]
    titles = _titles(nd.headlines_only(arts), "경제·증시")
    assert "스마트팩토리 설비 확대" not in titles and len(titles) == 2


def test_crypto_news_in_any_feed_moves_to_coin_and_general_feeds_get_classified():
    arts = [_a("NYT", "미국", "IT·과학", "Binance says hackers plotted $6.3 billion crypto heist"),
            _a("CBS News", "미국", "종합", "Ceasefire talks resume as Russia strikes Ukraine"),
            _a("Fox News", "미국", "종합", "Local school board votes on bus routes")]
    d = nd.headlines_only(arts)
    assert any("Binance" in t for t in _titles(d, "코인"))
    assert any("Ceasefire" in t for t in _titles(d, "세계 이슈"))
    assert any("school board" in t for t in _titles(d, "정치·사회"))
    assert "종합" not in [sec["topic"] for sec in d["sections"]]


def test_entry_time_parses_formats_feedparser_misses():
    utc = nd.timezone.utc
    assert nd._entry_time({"published": "2026-11-04T10:20:00+09:00"}) == datetime(2026, 11, 4, 1, 20, tzinfo=utc)
    assert nd._entry_time({"published": "Wed,4 Nov 2026 07:18:49 +0900"}) == datetime(2026, 11, 3, 22, 18, 49, tzinfo=utc)
    assert nd._entry_time({"updated": "2026-11-04 08:15:00"}) == datetime(2026, 11, 3, 23, 15, tzinfo=utc)  # 표기 없으면 KST
    assert nd._entry_time({}) is None


def _rss_file(tmp_path, name, items):
    body = "".join(f"<item><title>{t}</title><link>{l}</link><pubDate>{d}</pubDate></item>" for t, l, d in items)
    f = tmp_path / f"{name}.xml"
    f.write_text(f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{body}</channel></rss>',
                 encoding="utf-8")
    return str(f)


NOW = datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)
D_NEW, D_36H, D_OLD = ("Wed, 04 Nov 2026 01:00:00 GMT", "Mon, 02 Nov 2026 15:00:00 GMT", "Fri, 30 Oct 2026 00:00:00 GMT")


def test_per_feed_age_and_item_overrides(tmp_path):
    url = _rss_file(tmp_path, "art", [("new", "https://ex.com/1", D_NEW), ("old-ish", "https://ex.com/2", D_36H),
                                      ("ancient", "https://ex.com/3", D_OLD)])
    base = {"outlet": "ARTnews", "region": "미국", "category": "문화예술", "url": url}
    short = nd.fetch_articles({"feeds": [base], "max_age_hours": 26}, now=NOW)
    long_ = nd.fetch_articles({"feeds": [{**base, "max_age_hours": 48}], "max_age_hours": 26}, now=NOW)
    capped = nd.fetch_articles({"feeds": [{**base, "max_age_hours": 48, "max_items": 1}]}, now=NOW)
    assert [a.title for a in short] == ["new"]
    assert [a.title for a in long_] == ["new", "old-ish"]       # 미술 매체는 더 긴 기간 허용
    assert len(capped) == 1


def test_same_story_with_jonghap_suffix_is_deduplicated(tmp_path):
    url = _rss_file(tmp_path, "y", [("北 미사일 도발(종합2보)", "https://ex.com/a", D_NEW),
                                    ("北 미사일 도발(종합)", "https://ex.com/b", D_NEW),
                                    ("[속보] 北 미사일 도발", "https://ex.com/c", D_NEW)])
    arts = nd.fetch_articles({"feeds": [{"outlet": "연합", "region": "국내", "category": "세계 이슈", "url": url}]}, now=NOW)
    assert len(arts) == 1


def test_scheduled_run_skips_links_from_previous_digest_but_manual_run_does_not(tmp_path, monkeypatch):
    import io
    issues = [{"title": "[뉴스 브리핑] 11/03 x", "body": "- **[어제 기사](https://ex.com/a?utm=1)** 요약"},
              {"title": "[뉴스 브리핑] 11/02 y", "body": "[더 옛날](https://ex.com/z)"},   # 최신 1개만 사용
              ]

    class _Resp:
        def __enter__(self): return io.StringIO(json.dumps(issues))
        def __exit__(self, *a): pass

    monkeypatch.setattr(nd.urllib.request, "urlopen", lambda req, timeout=0: _Resp())
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/news")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    url = _rss_file(tmp_path, "d", [("어제 기사", "https://ex.com/a?utm=2", D_NEW), ("오늘 기사", "https://ex.com/b", D_NEW),
                                    ("더 옛날 기사", "https://ex.com/z", D_NEW)])
    cfg = {"feeds": [{"outlet": "A", "region": "국내", "category": "세계 이슈", "url": url}]}
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    assert [a.title for a in nd.fetch_articles(cfg, now=NOW)] == ["오늘 기사", "더 옛날 기사"]
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")      # 수동 실행은 전체 표시
    assert len(nd.fetch_articles(cfg, now=NOW)) == 3


def test_previous_digest_failure_is_non_fatal(monkeypatch):
    def boom(req, timeout=0):
        raise OSError("network")
    monkeypatch.setattr(nd.urllib.request, "urlopen", boom)
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/news")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    assert nd.previous_digest_keys() == set()


def test_prompt_states_reader_focus_and_limits():
    for needle in ("예술가", "세계 이슈", "코인", "문화예술", "국내와 해외", "아이돌"):
        assert needle in nd.SYSTEM_PROMPT
    assert "문화예술 8개" in nd.SYSTEM_PROMPT and "세계 이슈 7개" in nd.SYSTEM_PROMPT


def test_clean_summary_strips_bylines_but_keeps_normal_text():
    assert nd._clean_summary("(서울=연합뉴스) 전명훈 기자 = 북한이 4일 미사일을") == "북한이 4일 미사일을"
    assert nd._clean_summary("[서울=뉴시스] 박현주 미술전문 기자 = 회화는 어떤 의미를") == "회화는 어떤 의미를"
    assert nd._clean_summary("[서울=뉴시스]이수지 기자 = 전통 재료와") == "전통 재료와"
    assert nd._clean_summary("[블록미디어 함지현 기자] 미국 중간선거에서") == "미국 중간선거에서"
    assert nd._clean_summary("(카이로=연합뉴스) 김상훈 특파원 = 이란이") == "이란이"
    assert nd._clean_summary("Israel's president begins   talks") == "Israel's president begins talks"
    assert nd._clean_summary("일반 문장입니다. 기자 = 이 아닌 경우") == "일반 문장입니다. 기자 = 이 아닌 경우"


def test_clip_adds_ellipsis_only_when_truncated():
    assert nd._clip("짧은 글", 120) == "짧은 글"
    assert nd._clip("a" * 130, 120) == "a" * 120 + "…"


def test_footer_does_not_claim_ai_summary_in_headlines_mode():
    day = datetime(2026, 11, 4)
    heads = nd.headlines_only([_art("A", "국내", "세계 이슈")])
    assert heads["ai"] is False
    for out in (nd.render_html(heads, day), nd.render_markdown(heads, day)):
        assert "AI 요약 없이" in out and "AI가 자동 요약한" not in out
    ai = {"headline": "h", "sections": []}
    assert "AI가 자동 요약한" in nd.render_html(ai, day) and "AI가 자동 요약한" in nd.render_markdown(ai, day)


GOOD_DIGEST = {"headline": "h", "sections": [{"topic": "세계 이슈", "overview": "핵심", "items": [
    {"title": "t", "summary": "s", "source": "A", "link": "https://ex.com/1"}]}]}


def _or_fake(monkeypatch, outcomes, seen=None, sleeps=None):
    """모델 이름별로 정해 둔 결과(예외·응답 dict, 또는 그 목록)를 돌려주는 가짜 urlopen."""
    import io
    sleeps = [] if sleeps is None else sleeps

    def fake(req, timeout=0):
        payload = json.loads(req.data)
        if seen is not None:
            seen.append((req, payload))
        out = outcomes[payload["model"]]
        if isinstance(out, list):            # 호출할 때마다 앞에서부터 하나씩 사용(마지막 값은 계속 반복)
            out = out.pop(0) if len(out) > 1 else out[0]
        if isinstance(out, Exception):
            raise out

        class _R:
            def __enter__(self): return io.StringIO(json.dumps(out))
            def __exit__(self, *a): pass
        return _R()

    monkeypatch.setattr(nd.urllib.request, "urlopen", fake)
    monkeypatch.setattr(nd.time, "sleep", lambda sec: sleeps.append(sec))    # 재시도 대기를 실제로 하지 않음
    monkeypatch.setenv("OPENROUTER_API_KEY", "SECRET-OR-KEY")


def _chat(text):
    return {"choices": [{"message": {"content": text}}]}


def test_openrouter_success_sends_key_only_in_header(monkeypatch):
    seen = []
    _or_fake(monkeypatch, {"m1": _chat(json.dumps(GOOD_DIGEST, ensure_ascii=False))}, seen)
    monkeypatch.setenv("OPENROUTER_MODELS", "m1")
    out = nd.summarize([_art("A", "국내", "세계 이슈")], "openrouter")
    assert out["sections"][0]["overview"] == "핵심"
    req, payload = seen[0]
    assert req.full_url == "https://openrouter.ai/api/v1/chat/completions"
    assert req.get_header("Authorization") == "Bearer SECRET-OR-KEY"
    assert "SECRET-OR-KEY" not in req.full_url and "SECRET-OR-KEY" not in json.dumps(payload)
    assert payload["messages"][0]["role"] == "system" and payload["max_tokens"] == 12000


def test_openrouter_falls_through_models_on_429_bad_json_and_empty(monkeypatch):
    seen = []
    _or_fake(monkeypatch, {
        "m1": _http_error(429, "rate limited"),
        "m2": _chat("죄송합니다. 요약할 수 없습니다."),                # JSON이 아님
        "m3": _chat(""),                                           # 빈 응답
        "m4": {"error": {"message": "provider down"}},             # 200이지만 에러만 있음
        "m5": _chat("```json\n" + json.dumps(GOOD_DIGEST, ensure_ascii=False) + "\n```"),
    }, seen)
    monkeypatch.setenv("OPENROUTER_MODELS", "m1,m2,m3,m4,m5")
    out = nd._call_openrouter("s", "u")
    assert json.loads(out.strip("`").split("\n", 1)[1].rsplit("```", 1)[0])["headline"] == "h"
    assert [p["model"] for _, p in seen] == ["m1", "m1", "m1", "m2", "m3", "m4", "m5"]   # m1은 429라 재시도 후 포기


def test_openrouter_auth_error_stops_immediately(monkeypatch):
    import pytest
    seen = []
    _or_fake(monkeypatch, {"m1": _http_error(401, "invalid key"), "m2": _chat("{}")}, seen)
    monkeypatch.setenv("OPENROUTER_MODELS", "m1,m2")
    with pytest.raises(RuntimeError, match="401"):
        nd._call_openrouter("s", "u")
    assert len(seen) == 1                                          # 키 오류는 다른 모델을 시도하지 않음


def test_openrouter_all_rate_limited_raises_quota(monkeypatch):
    import pytest
    _or_fake(monkeypatch, {"m1": _http_error(429, "x"), "m2": _http_error(429, "y")})
    monkeypatch.setenv("OPENROUTER_MODELS", "m1,m2")
    with pytest.raises(nd.QuotaExceeded):
        nd._call_openrouter("s", "u")


def test_openrouter_defaults_are_free_models():
    assert all(m.endswith(":free") or m == "openrouter/free" for m in nd.OPENROUTER_DEFAULT_MODELS)


def test_provider_chain_order_and_explicit(monkeypatch):
    for k in ("LLM_PROVIDER", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert nd.provider_chain() == []
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert nd.provider_chain() == ["gemini", "openrouter"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    assert nd.provider_chain() == ["anthropic", "gemini", "openrouter"]
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    assert nd.provider_chain() == ["openrouter"]
    monkeypatch.setenv("LLM_PROVIDER", "none")
    assert nd.provider_chain() == []


def test_main_falls_over_from_gemini_to_openrouter(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(nd, "fetch_articles", lambda cfg: [_art("A", "국내", "세계 이슈")])
    for k in ("LLM_PROVIDER", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    tried = []

    def fake_summarize(articles, provider):
        tried.append(provider)
        if provider == "gemini":
            raise nd.FreeTierUnavailable("403")      # 지금 실제 상황: 구글 무료 티어 불가
        return GOOD_DIGEST
    monkeypatch.setattr(nd, "summarize", fake_summarize)
    assert nd.main(["--dry-run"]) == 0
    html_out = (tmp_path / "digest.html").read_text(encoding="utf-8")
    assert tried == ["gemini", "openrouter"]
    assert "카테고리별 오늘의 핵심" in html_out and "헤드라인만" not in html_out
    assert "AI 요약 완료: openrouter" in capsys.readouterr().out


def test_main_all_providers_fail_uses_last_error_note(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(nd, "fetch_articles", lambda cfg: [_art("A", "국내", "세계 이슈")])
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")

    def fake_summarize(articles, provider):
        raise nd.FreeTierUnavailable("403") if provider == "gemini" else nd.QuotaExceeded("429")
    monkeypatch.setattr(nd, "summarize", fake_summarize)
    assert nd.main(["--dry-run"]) == 0
    assert "무료 사용 한도를 초과" in (tmp_path / "digest.html").read_text(encoding="utf-8")


def test_parse_json_ignores_trailing_text_and_second_object():
    # 실제 실패 사례: 첫 JSON 뒤에 군더더기가 붙어 'Extra data' 오류가 났음
    assert nd.parse_json('{"a": 1}\n{"b": 2}') == {"a": 1}
    assert nd.parse_json('```json\n{"a": 1}\n```\n\n참고: {이것은} 설명입니다') == {"a": 1}
    assert nd.parse_json('여기 결과입니다.\n{"a": {"b": [1, 2]}} 이상입니다.') == {"a": {"b": [1, 2]}}
    import pytest
    with pytest.raises(ValueError):
        nd.parse_json("JSON 없음")
    with pytest.raises(ValueError):
        nd.parse_json("{깨진 json")


def test_openrouter_accepts_response_with_trailing_garbage(monkeypatch):
    text = json.dumps(GOOD_DIGEST, ensure_ascii=False) + "\n\n위 요약은 기사 목록만 사용했습니다. {끝}"
    _or_fake(monkeypatch, {"m1": _chat(text)})
    monkeypatch.setenv("OPENROUTER_MODELS", "m1")
    assert nd.summarize([_art("A", "국내", "세계 이슈")], "openrouter")["headline"] == "h"


def test_openrouter_slow_model_is_abandoned_and_next_model_used(monkeypatch):
    import io
    import time as _time
    monkeypatch.setattr(nd, "OPENROUTER_REQUEST_SECONDS", 0.2)
    calls = []

    def fake(req, timeout=0):
        model = json.loads(req.data)["model"]
        calls.append(model)
        if model == "slow":
            _time.sleep(1.5)      # 응답이 오지 않는 모델

        class _R:
            def __enter__(self): return io.StringIO(json.dumps(_chat(json.dumps(GOOD_DIGEST, ensure_ascii=False))))
            def __exit__(self, *a): pass
        return _R()
    monkeypatch.setattr(nd.urllib.request, "urlopen", fake)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_MODELS", "slow,fast")
    t0 = _time.monotonic()
    out = nd._call_openrouter("s", "u")
    assert calls == ["slow", "fast"] and json.loads(out)["headline"] == "h"
    assert _time.monotonic() - t0 < 1.2          # 느린 모델을 끝까지 기다리지 않음


def test_openrouter_logs_every_failed_model_with_reason(monkeypatch, capsys):
    import pytest
    _or_fake(monkeypatch, {"m1": _http_error(429, "limit"), "m2": _chat("그냥 글입니다"), "m3": _chat("")})
    monkeypatch.setenv("OPENROUTER_MODELS", "m1,m2,m3")
    with pytest.raises(RuntimeError):
        nd._call_openrouter("s", "u")
    err = capsys.readouterr().err
    for needle in ("m1", "HTTP 429", "m2", "형식 오류", "그냥 글입니다", "m3", "빈 응답"):
        assert needle in err                      # 모델별 원인이 모두 로그에 남는다


def test_openrouter_retries_same_model_on_temporary_429_then_succeeds(monkeypatch, capsys):
    sleeps, seen = [], []
    good = _chat(json.dumps(GOOD_DIGEST, ensure_ascii=False))
    _or_fake(monkeypatch, {"m1": [_http_error(429, "temporarily rate-limited upstream"), _http_error(503, "busy"), good],
                           "m2": good}, seen, sleeps)
    monkeypatch.setenv("OPENROUTER_MODELS", "m1,m2")
    out = nd._call_openrouter("s", "u")
    assert json.loads(out)["headline"] == "h"
    assert [p["model"] for _, p in seen] == ["m1", "m1", "m1"]        # 같은 모델로 재시도해서 성공(m2는 쓰지 않음)
    assert sleeps == list(nd.OPENROUTER_RETRY_WAITS)                  # 20초, 45초 대기
    assert "모델 사용: m1" in capsys.readouterr().out


def test_openrouter_gives_up_on_model_after_retries_then_moves_on(monkeypatch):
    sleeps, seen = [], []
    good = _chat(json.dumps(GOOD_DIGEST, ensure_ascii=False))
    _or_fake(monkeypatch, {"m1": _http_error(429, "limit"), "m2": good}, seen, sleeps)
    monkeypatch.setenv("OPENROUTER_MODELS", "m1,m2")
    nd._call_openrouter("s", "u")
    assert [p["model"] for _, p in seen] == ["m1", "m1", "m1", "m2"]   # m1은 3번 시도 후 포기
    assert len(sleeps) == 2


def test_openrouter_empty_response_log_has_diagnostics(monkeypatch, capsys):
    import pytest
    empty = {"model": "nvidia/real-model", "usage": {"completion_tokens": 12000},
             "choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": None, "reasoning": "..."}}]}
    _or_fake(monkeypatch, {"m1": empty})
    monkeypatch.setenv("OPENROUTER_MODELS", "m1")
    with pytest.raises(RuntimeError):
        nd._call_openrouter("s", "u")
    err = capsys.readouterr().err
    for needle in ("빈 응답", "finish=length", "nvidia/real-model", "reasoning"):
        assert needle in err


def test_auth_errors_are_not_retried(monkeypatch):
    import pytest
    sleeps, seen = [], []
    _or_fake(monkeypatch, {"m1": _http_error(401, "bad key")}, seen, sleeps)
    monkeypatch.setenv("OPENROUTER_MODELS", "m1")
    with pytest.raises(RuntimeError, match="401"):
        nd._call_openrouter("s", "u")
    assert len(seen) == 1 and sleeps == []
