#!/usr/bin/env python3
"""매일 주요 뉴스를 수집 → AI로 요약 → 이메일 / 텔레그램 발송.

사용법:
    python news_digest.py              # 설정된 채널(이메일/텔레그램)로 모두 발송
    python news_digest.py --dry-run    # 발송 대신 digest.html 파일로 저장
    python news_digest.py --no-llm     # AI 호출 없이 헤드라인만 (비용 0원)

환경변수 (요약 엔진 — 아래 중 하나, 아무것도 없으면 헤드라인만 발송):
    LLM_PROVIDER        anthropic | gemini | none (생략 시 키가 있는 쪽을 자동 선택)
    ANTHROPIC_API_KEY   Claude API 키 (유료, 종량제)   CLAUDE_MODEL 기본 claude-sonnet-5-5
    GEMINI_API_KEY      Google Gemini API 키 (무료 티어는 프로젝트에 따라 불가)   GEMINI_MODEL 기본 gemini-3.8-flash
    OPENROUTER_API_KEY  OpenRouter 키 (무료 모델 사용 가능)   OPENROUTER_MODELS 쉼표로 지정(기본: 무료 모델 3종)
    ※ 키가 여러 개면 claude → gemini → openrouter 순으로 시도하고, 모두 실패하면 헤드라인만으로 대체해 발송합니다.

  [이메일] 아래가 모두 있으면 이메일 발송
    SMTP_HOST / SMTP_PORT  (기본 smtp.gmail.com / 465)
    SMTP_USER / SMTP_PASSWORD  SMTP 계정 (Gmail은 앱 비밀번호)
    MAIL_TO             수신자 (쉼표로 여러 명)
    MAIL_FROM           발신자 (기본 SMTP_USER)

  [텔레그램] 아래가 모두 있으면 텔레그램 발송
    TELEGRAM_BOT_TOKEN  @BotFather에서 받은 봇 토큰
    TELEGRAM_CHAT_ID    받을 채팅 ID (쉼표로 여러 개 가능)

  [GitHub 알림] GitHub Actions 안에서, 위 두 채널이 없으면 자동으로 사용 (입력할 키 없음)
    저장소에 이슈를 올리면 GitHub가 담당자(기본: 저장소 주인)에게 알림 메일을 보냄
    ISSUE_NOTIFY        true=다른 채널과 함께 사용 / false=끄기
    ISSUE_ASSIGNEES     알림받을 GitHub 사용자명 (쉼표로 여러 명, 저장소 접근 권한 필요)
"""
from __future__ import annotations

import argparse
import calendar
import email.utils
import html
import json
import os
import re
import smtplib
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import feedparser

KST = timezone(timedelta(hours=9))
CONFIG_PATH = Path(__file__).with_name("feeds.json")


# 독자가 중점적으로 보는 순서(세계 이슈 → 경제·증시 → 코인 → 문화예술)이며, 값은 카테고리별 최대 항목 수
CATEGORY_LIMITS = {"세계 이슈": 7, "경제·증시": 7, "코인": 4, "문화예술": 8,
                   "정치·사회": 4, "IT·과학": 3, "스포츠": 2}
CATEGORIES = list(CATEGORY_LIMITS)
MIN_DOMESTIC_ART = 3          # 문화예술에 국내 소식이 최소 몇 건 들어가야 하는지
FEED_FAILURES: list[str] = []  # 이번 실행에서 읽지 못한 매체(발송 하단에 표시)
LAST_MODEL_USED = ""           # 이번 요약에 실제 쓰인 AI 모델 이름(발송 하단에 표시)

# 헤드라인 모드(AI 없음)에서 카테고리별로 '관련 기사'를 우선 고르기 위한 키워드. (한글, 영어) 순이며
# 핵심어(core)는 가중치 3, 보조어(other)는 1. 영어는 단어 경계로, 한글은 부분 일치로 찾는다.
def _kw(ko: tuple, en: tuple) -> re.Pattern:
    pattern = "|".join(re.escape(k) for k in ko)
    if en:
        pattern += ("|" if pattern else "") + r"\b(?:" + "|".join(en) + r")\b"
    return re.compile(pattern, re.I)


KEYWORDS = {
    "세계 이슈": (
        _kw(("전쟁", "휴전", "종전", "정전", "미사일", "공습", "폭격", "제재", "정상회담", "외교", "안보", "침공", "점령",
             "분쟁", "우크라이나", "러시아", "이란", "이스라엘", "가자", "하마스", "헤즈볼라", "북한", "대만", "나토",
             "유엔", "중동", "호르무즈", "쿠데타", "파병", "국방", "핵"),
            ("war", "ceasefire", "truce", "strikes?", "missiles?", "sanctions", "summit", r"diplomat\w*", "treaty",
             "troops", "invasion", "nato", "ukraine", "russia", "iran", "israel", "gaza", "hamas", "taiwan",
             "north korea", "kremlin", "putin", r"zelensk\w*", "netanyahu", "hormuz", "military", "nuclear")),
        _kw(("대통령", "총리", "선거", "정상", "협상", "대사", "중국", "미중", "한미", "한일", "한중", "美", "中", "日", "北"),
            ("president", "minister", "election", "talks", "border", "tensions", "china", "g7", "g20", "eu"))),
    "경제·증시": (
        _kw(("증시", "코스피", "코스닥", "주가", "주식", "환율", "금리", "나스닥", "다우", "연준", "국채", "시황", "증권",
             "채권", "달러", "원화", "유가", "인플레", "물가", "상장", "공모주", "배당", "시총", "금융시장"),
            ("stocks?", "wall street", "fed", "nasdaq", r"s&p", "dow", "yields?", "inflation", "earnings", "shares",
             "equities", "bonds?", r"interest rates?", "gdp", "recession", "ipo", "dollar", "oil")),
        _kw(("투자", "실적", "영업이익", "매출", "수출", "무역", "관세", "부동산", "집값", "대출", "고용", "경기", "성장률",
             "은행", "반도체", "펀드"),
            ("markets?", "investors?", "profit", "revenue", "tariffs?", "trade", "bank", "economy", "economic",
             "prices?", "rally", "selloff", "rates?"))),
    "코인": (
        _kw(("비트코인", "이더리움", "코인", "가상자산", "암호화폐", "블록체인", "리플", "솔라나", "스테이블", "바이낸스",
             "업비트", "빗썸", "디파이", "토큰", "알트코인", "도지"),
            ("bitcoin", "btc", "ethereum", "ether", "eth", "crypto", "cryptocurrency", "stablecoins?", "binance",
             "coinbase", "solana", "ripple", "xrp", "defi", "blockchain", "tokens?", "altcoins?", "dogecoin",
             "tether", "nfts?")),
        _kw(("거래소", "ETF", "해킹", "NFT"), ("etf", "exchange", "wallet", "mining", "halving"))),
    "IT·과학": (
        _kw(("인공지능", "반도체", "로봇", "우주", "위성", "발사체", "데이터센터", "해킹", "사이버", "스마트폰", "클라우드",
             "양자", "챗GPT", "생성형", "과학", "연구진", "엔비디아", "오픈AI"),
            ("artificial intelligence", "chips?", "semiconductors?", "robots?", "robotics", "satellites?", "rockets?", "nasa",
             r"data ?centers?", "cyber\\w*", "hack\\w*", "quantum", "openai", "nvidia", "software", "researchers?", "scientists?")),
        _kw(("AI", "기술", "개발", "출시", "공개", "스타트업", "플랫폼", "앱", "통신", "전자"),
            ("ai", "tech", "technology", "startups?", "app", "launch\\w*", "model", "platform"))),
    "문화예술": (
        _kw(("미술", "전시", "갤러리", "화랑", "화가", "조각", "설치미술", "회화", "비엔날레", "트리엔날레", "아트페어", "옥션",
             "경매", "컬렉", "큐레이", "미술관", "박물관", "사진전", "판화", "도예", "공예"),
            ("art", "arts", "artists?", "artworks?", "galler(?:y|ies)", "museums?", "exhibitions?", "biennale",
             "biennial", "auction", "curators?", r"sculpt\w*", r"paint\w*", "installation", "photography",
             "ceramics?", "collectors?", "frieze", "moma", "louvre", "tate", "guggenheim")),
        _kw(("아트", "작가", "건축", "디자인", "공연", "연극", "뮤지컬", "오페라", "무용", "발레", "국악", "클래식", "오케스트라",
             "영화제", "영화", "문학", "소설", "시집", "시인", "출판", "레지던시", "문화재", "유물", "개관", "거장", "음악회"),
            ("theatre", "theater", "opera", "ballet", "dance", "orchestra", "symphony", "film", "novel", "poet",
             "poetry", "literature", "book", "design", r"architect\w*", "heritage", "concert", "music"))),
}
# 키워드로 가려 뽑을 때 점수 0인 기사를 버릴지(True) 채워 넣을지(False)
STRICT_CATEGORIES = {"경제·증시", "코인", "문화예술"}


@dataclass
class Article:
    outlet: str      # 신문사
    region: str      # 국내 / 미국 / 영국 / 기타 해외
    category: str    # 피드에 지정된 카테고리 힌트 (종합이면 LLM이 분류)
    title: str
    link: str
    summary: str
    published: datetime | None


# ---------- 수집 ----------

def _entry_time(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    # feedparser가 못 읽는 형식(예: 2026-11-04T10:20:00+09:00, 'Wed,4 Nov 2026 ...')은 직접 해석
    for key in ("published", "updated"):
        raw = (entry.get(key) or "").strip()
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = email.utils.parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)  # 시간대 표기가 없으면 국내 피드가 대부분이라 KST로 간주
        return dt.astimezone(timezone.utc)
    return None


def _norm_title(title: str) -> str:
    """'(종합)', '(종합2보)', '[속보]' 같은 접미사를 떼어 같은 사건의 속보/종합 기사를 중복으로 본다."""
    t = re.sub(r"\((?:종합|속보|\d보)[^)]*\)|\[(?:속보|단독|종합)\]", "", title)
    return re.sub(r"\s+", " ", t).strip()


def previous_digest_keys() -> set[str]:
    """가장 최근 브리핑 이슈에 이미 실린 기사 링크 (예약 실행에서 어제와 겹치는 기사를 빼는 데 사용)."""
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not (repo and token):
        return set()
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/issues?state=all&per_page=5&sort=created&direction=desc",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "news-digest"})
        with urllib.request.urlopen(req, timeout=20) as r:
            issues = json.load(r)
    except Exception as err:  # 중복 제거는 부가 기능이므로 실패해도 계속
        print(f"[warn] 이전 브리핑을 불러오지 못해 중복 제거를 건너뜁니다: {err}", file=sys.stderr)
        return set()
    keys: set[str] = set()
    for it in issues:
        if "pull_request" in it or not str(it.get("title", "")).startswith("[뉴스 브리핑]"):
            continue
        for url in re.findall(r"\]\((https?://[^)\s]+)\)", it.get("body") or ""):
            keys.add(url.replace("%29", ")").split("?")[0])
        break  # 가장 최근 브리핑 하나만
    return keys


def fetch_articles(config: dict, now: datetime | None = None) -> list[Article]:
    now = now or datetime.now(timezone.utc)
    default_age = config.get("max_age_hours", 26)
    per_feed_default = config.get("max_items_per_feed", 15)
    max_total = config.get("max_total_articles", 450)
    seen: set[str] = set()
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":  # 수동 실행은 전체를 보여주고, 매일 자동 실행만 어제와 겹침을 제외
        seen |= previous_digest_keys()
    socket.setdefaulttimeout(20)  # 응답 없는 피드 하나가 전체를 막지 않도록
    FEED_FAILURES.clear()

    def _parse(feed: dict):
        outlet = feed.get("outlet") or feed.get("name", "")
        try:
            parsed = feedparser.parse(feed["url"], agent="news-digest/1.0")
        except Exception as e:  # 한 피드가 죽어도 전체는 계속
            print(f"[warn] {outlet}: {e}", file=sys.stderr)
            FEED_FAILURES.append(outlet)
            return None
        if parsed.get("bozo") and not parsed.entries:
            print(f"[warn] {outlet}: 피드를 읽지 못했습니다", file=sys.stderr)
            FEED_FAILURES.append(outlet)
            return None
        return parsed

    # 병렬로 내려받되 결과는 feeds.json 순서대로 처리 (Actions 실행 시간 절약)
    with ThreadPoolExecutor(max_workers=8) as pool:
        parsed_feeds = list(pool.map(_parse, config["feeds"]))

    per_feed_lists: list[list[Article]] = []
    for feed, parsed in zip(config["feeds"], parsed_feeds):
        items: list[Article] = []
        if parsed is not None:
            outlet = feed.get("outlet") or feed.get("name", "")
            per_feed = feed.get("max_items", per_feed_default)
            cutoff = now - timedelta(hours=feed.get("max_age_hours", default_age))  # 업데이트가 느린 미술 매체는 더 길게
            for entry in parsed.entries:
                title = (entry.get("title") or "").strip()
                link = entry.get("link") or ""
                if not title or not link:
                    continue
                published = _entry_time(entry)
                if published and published < cutoff:
                    continue
                key = link.split("?")[0]
                tkey = _norm_title(title)
                if key in seen or tkey in seen:
                    continue
                seen.update({key, tkey})
                items.append(Article(
                    outlet=outlet,
                    region=feed.get("region", ""),
                    category=feed.get("category", "종합"),
                    title=title,
                    link=link,
                    summary=_excerpt(entry, feed.get("category", "종합")),
                    published=published,
                ))
                if len(items) >= per_feed:
                    break
        per_feed_lists.append(items)

    # 상한을 넘으면 한 매체가 독식하지 않도록 피드별로 한 건씩 번갈아 채택
    articles: list[Article] = []
    for rank in range(max((len(x) for x in per_feed_lists), default=0)):
        for items in per_feed_lists:
            if rank < len(items) and len(articles) < max_total:
                articles.append(items[rank])
    return articles


def _strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", text)).strip()


ART_EXCERPT_CHARS = 320   # 문화예술 기사의 발췌 길이(일반은 200자). 짧으면 모델이 없는 내용을 기억으로 채우는 일이 실측으로 확인됨


def _excerpt(entry, category: str) -> str:
    """기사 발췌. 문화예술은 RSS 요약이 인용구 한 줄뿐인 경우가 많아, 본문(content)이 더 길면 그 앞부분을 쓴다."""
    raw = _strip_html(entry.get("summary", "") or "")
    if category == "문화예술":
        content = entry.get("content") or []
        if content:
            alt = _strip_html(content[0].get("value", "") or "")
            if len(alt) > len(raw):
                raw = alt
    return _clip(_clean_summary(raw), ART_EXCERPT_CHARS if category == "문화예술" else 200)


def _clean_summary(text: str) -> str:
    """연합·뉴시스 등의 기사 앞머리 '(서울=연합뉴스) 홍길동 기자 =' 같은 바이라인을 제거하고 공백을 정리한다."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[\(\[][^\)\]]{1,40}[\)\]]\s*", "", text)                       # (서울=연합뉴스) / [서울=뉴시스]
    text = re.sub(r"^(?:[가-힣A-Za-z· ]{2,25}\s)?[가-힣]{2,4}(?:\s[가-힣]{2,8})?\s?(?:기자|특파원)\s*=\s*", "", text)  # 홍길동 (미술전문) 기자 =
    return text.strip()


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n].rstrip() + "…"


# ---------- 날씨 · 오늘의 한마디 ----------

WEATHER_CITIES = (("서울", 37.5665, 126.9780), ("대구", 35.8714, 128.6014), ("LA", 34.0522, -118.2437))
WMO_TEXT = {0: "맑음", 1: "대체로 맑음", 2: "구름 조금", 3: "흐림", 45: "안개", 48: "안개", 51: "약한 이슬비", 53: "이슬비",
            55: "강한 이슬비", 56: "어는 이슬비", 57: "어는 이슬비", 61: "약한 비", 63: "비", 65: "강한 비", 66: "어는 비", 67: "어는 비",
            71: "약한 눈", 73: "눈", 75: "강한 눈", 77: "싸락눈", 80: "약한 소나기", 81: "소나기", 82: "강한 소나기",
            85: "눈 소나기", 86: "강한 눈 소나기", 95: "천둥번개", 96: "천둥번개·우박", 99: "천둥번개·우박"}


def _fmt_deg(x: float) -> str:
    return f"{round(x)}°"


def _signed(x: float) -> str:
    r = round(x)
    return f"+{r}°" if r > 0 else (f"{r}°".replace("-", "−") if r < 0 else "0°")


def parse_weather(city: str, data: dict) -> dict | None:
    """Open-Meteo 응답 → 한 도시의 날씨 요약. 현지 기준 '오늘' 항목을 찾아 어제(바로 앞)와 비교한다."""
    daily, cur = data["daily"], data.get("current") or {}
    today = str(cur.get("time", ""))[:10]
    times = daily["time"]
    if today not in times or times.index(today) == 0:
        return None
    i = times.index(today)

    def v(key: str, idx: int, default=0.0):
        arr = daily.get(key) or []
        x = arr[idx] if idx < len(arr) else None
        return default if x is None else x

    hi, lo, hi_y, lo_y = v("temperature_2m_max", i), v("temperature_2m_min", i), v("temperature_2m_max", i - 1), v("temperature_2m_min", i - 1)
    avg_diff = ((hi + lo) - (hi_y + lo_y)) / 2
    mood = "어제보다 따뜻함" if avg_diff >= 2 else ("어제보다 쌀쌀함" if avg_diff <= -2 else "어제와 비슷함")
    rain, snow, prob = v("precipitation_sum", i), v("snowfall_sum", i), v("precipitation_probability_max", i)
    if snow >= 0.1:
        precip = f"눈 예보(강수확률 {round(prob)}%, 적설 약 {snow:.1f}cm)"
    elif rain >= 0.5 or prob >= 40:
        precip = f"비 예보(강수확률 {round(prob)}%, 약 {rain:.1f}mm)"
    else:
        precip = f"강수 가능성 낮음({round(prob)}%)"
    out = {"city": city, "date": today, "sky": WMO_TEXT.get(int(v("weather_code", i, 0)), "—"),
           "now": _fmt_deg(cur["temperature_2m"]) if cur.get("temperature_2m") is not None else "",
           "lo": _fmt_deg(lo), "hi": _fmt_deg(hi), "mood": mood,
           "diff": f"최고 {_signed(hi - hi_y)}, 최저 {_signed(lo - lo_y)}", "precip": precip}
    if i + 1 < len(times):
        out["tomorrow"] = f"{WMO_TEXT.get(int(v('weather_code', i + 1, 0)), '—')} {_fmt_deg(v('temperature_2m_min', i + 1))}/{_fmt_deg(v('temperature_2m_max', i + 1))}"
    return out


def fetch_weather(cities=WEATHER_CITIES) -> list[dict]:
    """서울·대구·LA 날씨(Open-Meteo, 키 불필요·무료). 도시별로 실패하면 그 도시만 빠지고 전체는 계속된다."""
    out = []
    for name, lat, lon in cities:
        url = ("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
            "latitude": lat, "longitude": lon, "timezone": "auto", "past_days": 1, "forecast_days": 2,
            "current": "temperature_2m,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,snowfall_sum"}))
        for attempt in range(2):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "news-digest/1.0"}), timeout=15) as r:
                    info = parse_weather(name, json.load(r))
                if info:
                    out.append(info)
                break
            except Exception as err:  # noqa: BLE001 - 날씨 실패는 뉴스 발송을 막지 않는다
                if attempt == 1:
                    print(f"[warn] 날씨({name}) 가져오기 실패: {err}", file=sys.stderr)
                else:
                    time.sleep(2)
    return out


def _weather_lines(digest: dict) -> list[str]:
    lines = []
    ref = None
    for w in digest.get("weather") or []:
        ref = ref or w["date"]
        tag = f"(현지 {int(w['date'][5:7])}/{int(w['date'][8:10])}일)" if w["date"] != ref else ""
        now = f" · 지금 {w['now']}" if w.get("now") else ""
        tomorrow = f" · 내일 {w['tomorrow']}" if w.get("tomorrow") else ""
        lines.append(f"{w['city']}{tag}: {w['sky']}{now} · 최저 {w['lo']} / 최고 {w['hi']} · {w['mood']}({w['diff']}) · {w['precip']}{tomorrow}")
    return lines


# 오늘의 한마디: 직접 쓴 짧은 응원 문장(인용이 아니라서 출처 오류가 없음). 날짜에 따라 하나씩 돌아가며 나온다.
DAILY_MESSAGES = (
    ("오늘 하루, 작은 한 걸음이면 충분해요.", "One small step is enough for today."),
    ("당신의 속도는 틀리지 않았어요.", "Your pace is not wrong."),
    ("오늘도 당신만의 방식으로 빛나면 돼요.", "Shine today in your own way."),
    ("시작하는 용기가 이미 절반의 성공이에요.", "The courage to begin is already half the work."),
    ("어제의 나보다 조금만 다정하게 시작해요.", "Start today a little kinder than yesterday."),
    ("좋은 일은 천천히, 그러나 분명히 오고 있어요.", "Good things are arriving, slowly but surely."),
    ("오늘의 작은 시도가 내일의 큰 길이 돼요.", "Today's small attempt becomes tomorrow's wide road."),
    ("서두르지 않아도 도착할 곳에는 도착해요.", "You don't have to rush to arrive where you're headed."),
    ("완벽하지 않아도 괜찮아요. 시작이 중요해요.", "It doesn't have to be perfect. Starting is what matters."),
    ("오늘 만나는 모든 순간에 호기심을 가져 봐요.", "Meet every moment today with curiosity."),
    ("당신의 창작은 세상에 꼭 필요한 이야기예요.", "What you create is a story the world needs."),
    ("숨을 깊게 쉬고, 천천히 시작해 봐요.", "Take a deep breath and begin slowly."),
    ("오늘은 나를 믿어 주는 날로 해요.", "Let today be a day you trust yourself."),
    ("작은 기쁨 하나를 찾는 하루가 되길 바라요.", "May you find one small joy today."),
    ("실수해도 괜찮아요. 거기서 새로운 길이 열려요.", "Mistakes are okay. New paths open from them."),
    ("지금 있는 그 자리에서 충분히 잘하고 있어요.", "You're doing well right where you are."),
    ("오늘의 햇살은 오직 오늘만 비춰요. 마음껏 누려요.", "Today's light shines only today. Enjoy it."),
    ("하고 싶은 일을 향해 한 가지만 해 보세요.", "Do just one thing toward what you want."),
    ("당신 안에는 아직 꺼내지 않은 아이디어가 많아요.", "There are many ideas in you not yet brought out."),
    ("느리게 가도 멈추지 않으면 괜찮아요.", "Going slowly is fine as long as you keep going."),
    ("오늘은 어제보다 한 뼘 더 자유로워요.", "Today you are a little freer than yesterday."),
    ("마음이 가는 쪽으로 한 발만 내디뎌 봐요.", "Take one step toward what your heart leans to."),
    ("당신의 시선은 세상을 새롭게 보게 해요.", "Your way of seeing helps the world look new."),
    ("오늘의 걱정은 오늘의 나보다 작아요.", "Today's worries are smaller than today's you."),
    ("차분히 시작하면 하루가 부드럽게 흘러가요.", "Begin calmly and the day flows gently."),
    ("당신은 이미 많은 것을 해냈어요. 오늘도 해낼 거예요.", "You've already done so much. You'll do it again today."),
    ("작은 친절 하나가 하루를 바꿔요.", "One small kindness can change a day."),
    ("오늘은 잘 쉬는 것도 중요한 일이에요.", "Resting well is important work too."),
    ("떠오르는 생각을 믿고 한 줄 적어 봐요.", "Trust the thought that arises and jot down a line."),
    ("아침이 와서 다시 시작할 수 있다는 건 선물이에요.", "That morning comes and you can begin again is a gift."),
    ("당신의 꾸준함은 조용하지만 강한 힘이에요.", "Your steadiness is quiet but strong."),
    ("오늘 할 수 있는 만큼만, 마음을 다해서.", "Do what you can today, with your whole heart."),
    ("좋은 하루는 좋은 마음에서 시작돼요.", "A good day begins with a good heart."),
    ("당신이 만드는 모든 선은 당신만의 목소리예요.", "Every line you make is your own voice."),
    ("바람이 불어도 나는 내 길을 갈 수 있어요.", "Even when the wind blows, I can walk my own path."),
    ("오늘도 세상은 당신의 색을 기다리고 있어요.", "The world is waiting for your colors today."),
    ("괜찮아요, 천천히 해도 돼요.", "It's okay. You can take your time."),
    ("한 번 웃고 시작하면 하루가 가벼워져요.", "Start with one smile and the day feels lighter."),
    ("지금의 노력은 반드시 어딘가에 쌓이고 있어요.", "Your effort now is surely adding up somewhere."),
    ("오늘 하루도 당신답게, 충분히 멋지게.", "Be yourself today, and that is wonderful enough."),
    ("새로운 하루는 새로운 가능성이에요.", "A new day is a new possibility."),
    ("마음에 여백을 두면 좋은 생각이 들어와요.", "Leave space in your mind and good ideas will come in."),
    ("할 수 있다는 믿음이 첫 번째 재료예요.", "Believing you can is the first ingredient."),
    ("오늘 만나는 사람에게 따뜻한 말 한마디를 건네 봐요.", "Offer one warm word to someone you meet today."),
    ("당신의 하루는 당신이 그리는 한 장의 그림이에요.", "Your day is a picture you are painting."),
    ("조금 흔들려도 괜찮아요. 균형은 움직이며 찾는 거예요.", "A little wobble is fine. Balance is found in motion."),
    ("오늘의 나에게 수고했다고 미리 말해 줘요.", "Tell today's you 'well done' in advance."),
    ("가장 좋은 작품은 아직 만들어지지 않았어요.", "Your best work hasn't been made yet."),
    ("어떤 날에도 당신의 가치는 그대로예요.", "Your worth stays the same on any day."),
    ("깊은 숨 한 번, 가벼운 마음 한 번.", "One deep breath, one lighter heart."),
    ("오늘도 힘차게, 하지만 다정하게.", "Be strong today, and gentle too."),
    ("꿈은 매일 조금씩 가까워지고 있어요.", "Your dream gets a little closer every day."),
    ("당신이 오늘 보는 풍경이 누군가의 영감이 될 거예요.", "What you see today may inspire someone."),
    ("지금 이 순간도 충분히 아름다워요.", "This very moment is beautiful enough."),
    ("용기는 크지 않아도 돼요. 한 뼘이면 돼요.", "Courage needn't be big. An inch is enough."),
    ("오늘도 호기심 하나를 주머니에 넣고 나가요.", "Step out today with one curiosity in your pocket."),
    ("힘들면 잠깐 쉬어가요. 길은 그대로 있어요.", "If it's hard, pause. The road will still be there."),
    ("당신은 생각보다 훨씬 잘 해내고 있어요.", "You're doing much better than you think."),
    ("좋은 하루 보내세요. 당신은 그럴 자격이 있어요.", "Have a good day. You deserve it."),
)


def daily_message(date: datetime) -> dict:
    ko, en = DAILY_MESSAGES[date.toordinal() % len(DAILY_MESSAGES)]
    return {"ko": ko, "en": en}


# ---------- 요약 ----------

SYSTEM_PROMPT = f"""당신은 한 사람의 독자를 위한 개인 뉴스 에디터입니다. 독자는 **예술가(현대미술 작가)**이며
세계 정세, 경제·시장, 예술계 소식을 꾸준히 알고 있어야 합니다.
국내외 여러 신문사의 기사 목록(각 줄: [번호] (국내/미국/영국/기타 해외|신문사|카테고리힌트) 제목 | 요약 | 링크)에서
오늘 가장 중요한 뉴스를 골라 카테고리별로 한국어로 요약하세요.

독자가 가장 중요하게 보는 세 영역 (분량도 이 순서·비중으로 배분):
1. 세계 이슈: 전쟁·분쟁, 국가 간 관계·외교·제재·안보, 선거 등 세계 정세. 한반도·동아시아 관련 소식도 포함.
2. 경제·시장: 국제·국내 경제, 주식(지수·환율·금리·주요 종목·실적)과 코인(비트코인·이더리움·규제·거래소·ETF)의 시장 동향.
   코인 기사는 '코인' 카테고리로, 주식·거시경제는 '경제·증시'로 나눕니다.
3. 문화예술: 국내외 미술계 소식을 최우선(전시, 미술관·갤러리, 비엔날레·아트페어, 옥션·미술시장, 작가·큐레이터 동정,
   수상·공모, 소장품·반환·복원 이슈)으로 하고, 그다음 공연·영화·문학·건축·디자인. 국내 소식과 해외 소식을 모두 담으세요.
   아이돌·연예인 가십, 방송 화제성 기사는 예술계 맥락이 없으면 제외합니다.
   문화예술에는 **국내(한국) 매체의 국내 소식을 최소 3건** 반드시 포함하세요(목록에 있다면).

규칙:
- 카테고리는 다음 순서로 고정: {", ".join(CATEGORIES)}. 기사 목록에 해당 기사가 있으면 **모든 카테고리를 빠짐없이 포함**하세요
  (정치·사회, IT·과학, 스포츠도 생략하지 말고 상한 이내로 짧게). 기사가 전혀 없을 때만 생략합니다.
  '카테고리힌트'는 참고만 하고, 내용에 맞게 직접 분류하세요('종합'은 직접 판단).
- 카테고리별 항목 수 상한: {", ".join(f"{c} {n}개" for c, n in CATEGORY_LIMITS.items())}. 중요한 기사가 부족하면 적게 담고,
  정치·사회/IT·과학/스포츠는 짧게 유지하세요. 전체 25~35개.
- 같은 사건을 여러 신문사가 다뤘으면 하나로 묶고, source에 보도한 신문사를 모두(최대 3곳) 적으세요.
  국내·미국·영국 등 여러 나라 매체를 골고루 반영하고, 시각 차이가 있으면 summary에 한 문장으로 덧붙이세요.
- 각 항목 summary는 1~2문장. 사실 위주로, 과장·추측 금지.
- 경기 결과(승패·점수), 수치, 따옴표 인용은 제목·발췌문에 명시된 것만 쓰세요. 승패나 원인을 추정하지 마세요.
- '~할 예정', 'to give', 'will', 'plans to'처럼 예고·계획을 다룬 기사는 이미 일어난 일처럼 쓰지 말고 '예정', '추진'으로 표현하세요.
- 제목·발췌문에 없는 세부 묘사(장소·원인·평가·배경)를 덧붙이지 마세요. 작품명·인물 직함·위치 같은 정보를 당신이 알고 있는 지식으로 보충하지 마세요.
  발췌문이 짧아 내용이 불분명하면 제목에 있는 사실만 쓰세요.
- 같은 기사(링크)는 한 카테고리에만 넣으세요.
- 기사 목록에 없는 내용은 절대 만들어내지 마세요. link는 목록에 있는 대표 링크 그대로.
- 해외 기사는 한국어로 번역해 요약하세요. 작가·전시·기관 이름은 원어를 병기하세요(예: 쿠사마 야요이(Yayoi Kusama)).
- 각 카테고리에는 overview를 반드시 넣으세요. 그 분야에서 오늘 가장 큰 이슈가 무엇이고 항목들이
  어떻게 이어지는지를 2~3문장으로 설명하는 종합 요약입니다(항목 제목을 그대로 나열하지 말 것).
  문화예술의 overview는 국내와 해외 소식을 구분해서 설명하세요.
  items에 담은 내용과 기사 목록에 있는 사실만 쓰고, 목록에 없는 배경·전망을 지어내지 마세요.
- 반드시 아래 JSON만 출력하세요 (설명, 코드펜스 없이):
{{"headline": "오늘의 한 줄 요약", "sections": [{{"topic": "카테고리", "overview": "카테고리 핵심 요약 2~3문장", "items": [{{"title": "제목", "summary": "요약", "source": "신문사1, 신문사2", "link": "URL"}}]}}]}}"""


def provider_chain() -> list[str]:
    """요약에 시도할 AI 공급자 순서. LLM_PROVIDER가 있으면 그것만, 없으면 키가 설정된 곳을
    claude → gemini → openrouter 순으로 모두(앞이 실패하면 다음으로 넘어감). 비어 있으면 헤드라인 모드."""
    explicit = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if explicit == "none":
        return []
    if explicit in ("anthropic", "gemini", "openrouter"):
        return [explicit]
    keys = (("anthropic", "ANTHROPIC_API_KEY"), ("gemini", "GEMINI_API_KEY"), ("openrouter", "OPENROUTER_API_KEY"))
    return [name for name, env in keys if os.environ.get(env)]


def pick_provider() -> str:
    """시도할 첫 번째 공급자(없으면 none)."""
    chain = provider_chain()
    return chain[0] if chain else "none"


def _call_anthropic(system: str, user: str) -> str:
    import anthropic  # 이 엔진을 쓸 때만 필요

    msg = anthropic.Anthropic().messages.create(
        model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"),
        max_tokens=12000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if b.type == "text").strip()


class QuotaExceeded(RuntimeError):
    """무료 사용 한도(요청 수/토큰 수)를 초과했다. 한도가 다시 채워지면 다음 실행부터 정상 동작한다."""


class ModelUnavailable(RuntimeError):
    """지정한 AI 모델이 없어졌거나 이름이 바뀌었다(HTTP 404 등). 모델 목록(OPENROUTER_MODELS)을 고쳐야 한다."""


class FreeTierUnavailable(RuntimeError):
    """이 키가 속한 Google 프로젝트에는 Gemini 무료 티어가 제공되지 않는다(HTTP 403)."""


NO_FREE_NOTE = "이 키의 Google 프로젝트에서는 Gemini 무료 티어를 쓸 수 없어 헤드라인만 제공합니다 (새 프로젝트에서 키를 다시 발급해 보세요)"
QUOTA_NOTE = "무료 사용 한도를 초과해 오늘은 헤드라인만 제공합니다 (한도가 다시 채워지면 다음 발송부터 자동으로 요약이 돌아옵니다)"
MODEL_NOTE = ("지정된 무료 AI 모델이 OpenRouter에서 사라졌거나 이름이 바뀌어 헤드라인만 제공합니다 "
              "(저장소 Settings → Secrets and variables → Actions → Variables 의 OPENROUTER_MODELS 를 지우거나 새 모델 이름으로 바꾸세요)")
FAIL_NOTE = "AI 요약에 실패해 헤드라인만 제공합니다 (키/모델 설정을 확인하세요)"


def _call_gemini(system: str, user: str) -> str:
    model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "maxOutputTokens": 12000, "temperature": 0.1},
    }).encode()
    # 키는 URL이 아닌 헤더로 보내 로그/예외에 노출되지 않게 함
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    for attempt in range(3):  # 무료 티어의 일시적 한도(429)/과부하(503)는 잠시 후 재시도
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
            break
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:600]
            # '하루 한도'를 다 쓴 경우는 기다려도 소용없으므로 재시도하지 않는다
            daily = "perday" in detail.lower().replace(" ", "").replace("_", "")
            if err.code in (429, 503) and not (err.code == 429 and daily) and attempt < 2:
                time.sleep(30 * (attempt + 1))
                continue
            if err.code == 429:
                exc = QuotaExceeded
            elif err.code == 403 and "free tier is not available" in detail.lower():
                exc = FreeTierUnavailable
            else:
                exc = RuntimeError
            raise exc(f"Gemini API 오류 (HTTP {err.code}): {detail[:300]}") from None
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts).strip()


# OpenRouter 무료(:free) 모델. 무료 모델 목록은 수시로 바뀌므로 위에서부터 차례로 시도하고,
# OPENROUTER_MODELS(쉼표 구분)로 바꿀 수 있다. 실측 결과(2026-11-04, 같은 기사 450건·추론 끄기):
#  - nvidia/nemotron-3-ultra-550b-a55b:free : 98초, 자연스러운 한국어·정확한 요약 → 1순위
#  - google/gemma-4-31b-it:free, gemma-4-26b-a4b-it:free : 구글 쪽 429(한도)로 자주 막히지만 열려 있으면 빠름 → 2·3순위
#  - dots-studio/dots-3-note-preview:free : 중국어 혼입·지명 오류·없는 사건 서술 → 제외(오역·허위 요약은 헤드라인 모드보다 나쁨)
#  - openrouter/free(자동 라우터) : 위 모델로 연결될 수 있고 추론 모델로 빠지는 일이 잦아 제외
#  - thinkingmachines/inkling*:free : 에이전트 앱 전용(403) → 제외
# 추론을 끌 수 없는 모델(liquid/lfm, recursive/flint, stealth/crouton)도 쓰지 않는다.
# 순서: Nemotron → Gemma 31B → Nemotron(일시 오류 대비 한 번 더) → Gemma 26B. 전체 시간 상한(420초)이 넘으면 남은 시도는 건너뛴다.
OPENROUTER_DEFAULT_MODELS = (
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-26b-a4b-it:free",
)
OPENROUTER_REASONING_OFF = {"effort": "none"}  # 추론 끄기(문서: reasoning.effort="none" → 추론 완전 비활성화)
OPENROUTER_REQUEST_SECONDS = 150   # 모델 1개당 최대 대기 시간(응답 전체 기준)
OPENROUTER_BUDGET_SECONDS = 360    # 모든 모델을 합친 최대 시도 시작 시한(이후엔 새 시도를 시작하지 않음)


def _post_with_deadline(req: urllib.request.Request, seconds: float) -> dict:
    """urllib의 timeout은 '소켓이 조용한 시간'만 재서, 느리게 이어지는 응답은 오래 매달릴 수 있다.
    그래서 응답 전체에 걸리는 시간을 직접 제한한다(시간이 지나면 포기하고 다음 모델로)."""
    box: dict = {}

    def run() -> None:
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                box["data"] = json.load(r)
        except BaseException as err:  # noqa: BLE001 - 호출한 쪽으로 그대로 전달
            box["err"] = err

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError(f"{seconds:.0f}초 안에 응답이 없어 중단했습니다")
    if "err" in box:
        raise box["err"]
    return box["data"]


OPENROUTER_RETRY_WAITS = (20,)  # 일시적 한도(429)·서버 오류(5xx)는 이만큼 기다렸다가 같은 모델로 1회 재시도(실측: 더 기다려도 풀리지 않음)


def _call_openrouter(system: str, user: str, check=None, budget: float | None = None,
                     request_seconds: float | None = None) -> str:
    global LAST_MODEL_USED
    budget = OPENROUTER_BUDGET_SECONDS if budget is None else budget
    request_seconds = OPENROUTER_REQUEST_SECONDS if request_seconds is None else request_seconds
    unavailable: list[str] = []
    key = os.environ["OPENROUTER_API_KEY"]
    models = [m.strip() for m in os.environ.get("OPENROUTER_MODELS", "").split(",") if m.strip()] \
        or list(OPENROUTER_DEFAULT_MODELS)
    start = time.monotonic()
    last: Exception | None = None

    def fail(model: str, t0: float, reason: str, exc_type: type = RuntimeError) -> Exception:
        msg = f"OpenRouter 실패 ({model}, {time.monotonic() - t0:.0f}초): {reason}"
        print(f"[warn] {msg}", file=sys.stderr)  # 모델마다 이유를 모두 남겨 원인을 추적할 수 있게 함
        return exc_type(msg)

    def make_req(model: str, reasoning_off: bool) -> urllib.request.Request:
        payload = {"model": model,
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                   "temperature": 0.1, "max_tokens": 12000}
        if reasoning_off:
            payload["reasoning"] = OPENROUTER_REASONING_OFF
        return urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",
                                      data=json.dumps(payload).encode(), headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com", "X-OpenRouter-Title": "news-digest"})  # 키는 헤더로만 전송

    for model in models:
        reasoning_off, retries = True, 0
        req = make_req(model, reasoning_off)
        data, t0 = None, time.monotonic()
        for attempt in range(len(OPENROUTER_RETRY_WAITS) + 2):  # +1: 재시도, +1: 추론 옵션 제외 재요청
            if time.monotonic() - start > budget:
                print("[warn] OpenRouter 전체 시도 시간 상한을 넘어 남은 시도는 건너뜁니다", file=sys.stderr)
                break
            t0 = time.monotonic()
            try:
                data = _post_with_deadline(req, request_seconds)
                break
            except urllib.error.HTTPError as err:
                detail = err.read().decode("utf-8", "replace")[:300]
                last = fail(model, t0, f"HTTP {err.code} {detail}", QuotaExceeded if err.code == 429 else RuntimeError)
                if err.code in (401, 402, 403):  # 키/권한 문제는 다른 모델로 바꿔도 소용없음
                    raise last from None
                if err.code == 404 or (err.code == 400 and "model" in detail.lower() and
                                       any(w in detail.lower() for w in ("not a valid", "not found", "no endpoints"))):
                    unavailable.append(model)  # 모델이 사라졌거나 이름이 바뀜 → 다음 모델로
                    break
                if err.code == 400 and reasoning_off and "reasoning" in detail.lower():
                    reasoning_off = False  # 이 모델이 '추론 끄기'를 거부하면 그 옵션만 빼고 같은 모델로 다시
                    req = make_req(model, reasoning_off)
                    continue
                if err.code in (429, 500, 502, 503, 504) and retries < len(OPENROUTER_RETRY_WAITS):
                    time.sleep(OPENROUTER_RETRY_WAITS[retries])  # 잠시 후 같은 모델로 재시도
                    retries += 1
                    continue
                break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
                last = fail(model, t0, f"{type(err).__name__}: {err}")
                break  # 느린 모델/연결 오류는 재시도하지 않고 다음 모델로
        if data is None:
            if time.monotonic() - start > budget:
                break
            continue
        choice = (data.get("choices") or [{}])[0] if isinstance(data, dict) else {}
        message = choice.get("message") or {}
        text = (message.get("content") or "").strip() if isinstance(message, dict) else ""
        if not text:  # 200이어도 본문에 error만 오거나 비어 있는 경우(추론에 토큰을 다 쓴 모델 등)
            last = fail(model, t0, f"빈 응답 finish={choice.get('finish_reason')} usage={data.get('usage')} "
                                   f"실제모델={data.get('model')} 메시지키={list(message) if isinstance(message, dict) else message} "
                                   f"error={str(data.get('error'))[:150]}")
            continue
        try:
            if check:
                check(text)  # 형식·링크·항목 수 검증(부실하면 ValueError)
            elif not parse_json(text).get("sections"):
                raise ValueError("sections 없음")
        except ValueError as err:  # 형식을 못 맞추거나 부실한 응답이면 다음 모델로
            last = fail(model, t0, f"형식 오류({err}) 길이={len(text)}자 앞부분={text[:120]!r} 끝부분={text[-120:]!r}")
            continue
        print(f"OpenRouter 모델 사용: {model} → 실제 {data.get('model')} ({time.monotonic() - t0:.0f}초)")
        LAST_MODEL_USED = str(data.get("model") or model)
        return text
    if unavailable:
        raise ModelUnavailable(f"OpenRouter 모델을 찾을 수 없습니다: {', '.join(dict.fromkeys(unavailable))}")
    raise last or RuntimeError("OpenRouter 호출에 실패했습니다")


MIN_AI_ITEMS = 8  # 기사가 충분할 때 AI 요약이 최소한 담아야 하는 항목 수(이보다 적으면 부실한 응답으로 보고 다음 모델/공급자로)


def _link_key(url: str) -> str:
    return url.split("?")[0].rstrip("/").lower()


_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{3,}")
_KANA = re.compile(r"[\u3040-\u30ff]")
_CJK_ANY = re.compile(r"[\u4e00-\u9fff]")
_PAREN = re.compile(r"[\(（][^\)）]*[\)）]")
_NUM = re.compile(r"\d[\d,.]*\d|\d")
_SCORE = re.compile(r"\d+\s*[-–:]\s*\d+")


def _garbled(text: str) -> bool:
    """한국어 요약에 한자·일본어가 섞여 나온 경우(무료 모델의 오역 징후). 괄호 안의 원어 병기(村上隆 등)와
    '美·中'처럼 한 글자짜리 약칭은 허용한다."""
    t = _PAREN.sub(" ", text)
    return bool(_CJK_RUN.search(t) or _KANA.search(t) or len(_CJK_ANY.findall(t)) >= 6)


def _unsupported_numbers(text: str, source: str) -> list[str]:
    """text에 나온 숫자 중 근거 글(source)에 없는 것. 모델이 지어낸 점수·금액을 걸러낸다(연도 20xx는 허용)."""
    src = source.replace(",", "")
    bad = []
    for n in _NUM.findall(text):
        n = n.replace(",", "").rstrip(".")
        if n and not re.fullmatch(r"20\d\d", n) and n not in src:
            bad.append(n)
    return bad


def _unsupported_scores(text: str, source: str) -> list[str]:
    """'0-3' 같은 점수 표기 중 원문(제목·발췌)에 없는 것. 경기 결과를 뒤집어 쓰는 오류(실측: 승리한 경기를 0-3 패배로 서술)를 잡는다."""
    src = re.sub(r"\s+", "", source)
    return [m for m in _SCORE.findall(text) if re.sub(r"\s+", "", m) not in src]


def validate_digest(digest: dict, articles: list[Article], verbose: bool = False) -> dict:
    """AI가 만든 요약을 코드로 검증·정리한다(지시문만으로는 막을 수 없는 오류 방지).
    - 수집한 기사 목록에 없는 링크의 항목은 버린다 → 지어낸/조작된 링크 차단
    - 같은 링크는 먼저 나온 카테고리에만 남긴다
    - 카테고리별 항목 수를 CATEGORY_LIMITS로 제한한다
    - 한자·일본어가 섞인 항목은 버린다(오역 징후)
    - 핵심 요약(overview)·한 줄 요약에 근거 없는 숫자(점수·금액 등)가 있으면 그 문장을 비운다
    - 항목이 하나도 없는 카테고리는 뺀다
    정리 후 항목이 너무 적으면 ValueError(호출한 쪽이 다음 모델/공급자로 넘어간다)."""
    by_key = {_link_key(a.link): a for a in articles}
    seen: set[str] = set()
    dropped = {"없는 링크": 0, "중복": 0, "상한 초과": 0, "깨진 문자": 0, "근거 없는 숫자": 0, "근거 없는 점수": 0}
    sections = []
    for sec in digest.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        limit = CATEGORY_LIMITS.get(str(sec.get("topic", "")), 5)
        items = []
        for it in sec.get("items") or []:
            if not isinstance(it, dict):
                continue
            key = _link_key(str(it.get("link", "")))
            if key not in by_key:
                dropped["없는 링크"] += 1
            elif key in seen:
                dropped["중복"] += 1
            elif _garbled(f"{it.get('title', '')} {it.get('summary', '')}"):
                dropped["깨진 문자"] += 1
            elif len(items) >= limit:
                dropped["상한 초과"] += 1
            else:
                seen.add(key)
                srcs = [x.strip() for x in str(it.get("source", "")).split(",") if x.strip()]
                it = {**it, "source": ", ".join(srcs[:3])}  # 출처는 최대 3곳
                art = by_key[key]
                if _unsupported_scores(f"{it.get('title', '')} {it.get('summary', '')}", f"{art.title} {art.summary}"):
                    # 원문에 없는 점수 → AI 서술을 버리고 원문 제목·발췌로 대체(틀린 결과보다 영어 원문이 낫다)
                    it = {**it, "title": html.unescape(art.title), "summary": _clip(art.summary, 120)}
                    dropped["근거 없는 점수"] += 1
                items.append(it)
        if items:
            ov = str(sec.get("overview") or "").strip()
            evidence = " ".join(f"{it.get('title', '')} {it.get('summary', '')} "
                                f"{by_key[_link_key(str(it.get('link', '')))].title} "
                                f"{by_key[_link_key(str(it.get('link', '')))].summary}" for it in items)
            if ov and (_garbled(ov) or _unsupported_numbers(ov, evidence)):
                dropped["근거 없는 숫자"] += 1
                ov = ""  # 틀릴 위험이 있는 문장은 쓰지 않는다(2차 재작성에서 다시 쓰게 함)
            sections.append({**sec, "overview": ov, "items": items})
    if dropped["깨진 문자"] >= 3:
        raise ValueError(f"AI 요약에 한자·일본어가 섞인 항목이 {dropped['깨진 문자']}개 있어 오역으로 판단합니다")
    total = sum(len(x["items"]) for x in sections)
    need = min(MIN_AI_ITEMS, max(1, len(articles) // 20))
    if total < need:
        raise ValueError(f"AI 요약이 부실합니다: 유효 항목 {total}개 (최소 {need}개 필요, 제거 {dropped})")
    headline = str(digest.get("headline") or "").strip()
    all_text = " ".join(f"{it.get('title', '')} {it.get('summary', '')}" for x in sections for it in x["items"])
    if not headline or _garbled(headline) or _unsupported_numbers(headline, all_text):
        first = sections[0]["items"][0].get("title", "") if sections else ""
        headline = _clip(first, 60) or "오늘의 주요 뉴스"
    if verbose and any(dropped.values()):
        print(f"AI 요약 정리: 항목 {total}개 유지, 제거 {dropped}")
    return {**digest, "headline": headline, "sections": sections}


def backfill_missing_categories(digest: dict, articles: list[Article]) -> dict:
    """AI가 일부 카테고리를 통째로 빠뜨렸으면(실측: 정치·사회/IT·과학/스포츠 생략) 그 카테고리를 원문 헤드라인으로 보충한다."""
    have = {x.get("topic") for x in digest.get("sections", [])}
    missing = [c for c in CATEGORIES if c not in have]
    if not missing:
        return digest
    used = {_link_key(it.get("link", "")) for x in digest["sections"] for it in x.get("items", [])}
    extra = []
    for sec in headlines_only(articles)["sections"]:
        if sec["topic"] not in missing:
            continue
        items = [it for it in sec["items"] if _link_key(it["link"]) not in used]
        if items:
            extra.append({"topic": sec["topic"], "overview": "AI 요약에서 빠져 원문 헤드라인으로 보충했습니다.",
                          "backfilled": True, "items": items})
    order = {c: i for i, c in enumerate(CATEGORIES)}
    sections = sorted(digest["sections"] + extra, key=lambda x: order.get(x.get("topic"), len(order)))
    return {**digest, "sections": sections}


def ensure_domestic_art(digest: dict, articles: list[Article], minimum: int = MIN_DOMESTIC_ART) -> dict:
    """문화예술에 국내 소식이 minimum건보다 적으면, 국내 매체의 미술·문화 기사를 원문 헤드라인으로 채운다
    (독자가 국내 예술계 소식을 꼭 봐야 하므로 AI가 해외 기사만 고르는 날을 막는다)."""
    by_key = {_link_key(a.link): a for a in articles}
    sections = [dict(x) for x in digest.get("sections", [])]
    sec = next((x for x in sections if x.get("topic") == "문화예술"), None)
    items = list(sec["items"]) if sec else []

    def domestic(it: dict) -> bool:
        a = by_key.get(_link_key(str(it.get("link", ""))))
        return bool(a and a.region == "국내")

    have = sum(1 for it in items if domestic(it))
    if have >= minimum:
        return digest
    used = {_link_key(str(it.get("link", ""))) for x in sections for it in x.get("items", [])}
    cands = sorted((a for a in articles if a.region == "국내" and _link_key(a.link) not in used
                    and ((a.category == "문화예술" and art_score(a) > 0) or art_score(a) >= 6)),
                   key=lambda a: -art_score(a))
    added, per_outlet = [], {}
    for a in cands:
        if have + len(added) >= minimum:
            break
        if per_outlet.get(a.outlet, 0) >= 2:
            continue
        per_outlet[a.outlet] = per_outlet.get(a.outlet, 0) + 1
        added.append({"title": html.unescape(a.title), "summary": _clip(a.summary, 120),
                      "source": a.outlet, "link": a.link})
    if not added:
        return digest
    limit = CATEGORY_LIMITS["문화예술"]
    while len(items) + len(added) > limit:  # 자리가 모자라면 뒤쪽의 해외 항목부터 덜어낸다
        idx = next((i for i in range(len(items) - 1, -1, -1) if not domestic(items[i])), None)
        if idx is None:
            break
        items.pop(idx)
    if sec:
        sec["items"] = items + added
    else:
        sections.append({"topic": "문화예술", "overview": "", "items": added})
    order = {c: i for i, c in enumerate(CATEGORIES)}
    sections.sort(key=lambda x: order.get(x.get("topic"), len(order)))
    return {**digest, "sections": sections}


REFINE_PROMPT = """당신은 뉴스 에디터입니다. 아래는 이미 확정된 카테고리별 뉴스 항목입니다
(각 줄: - [국내/미국/영국/기타 해외] 제목 – 요약 (출처)).
각 카테고리마다 **그 항목들만 근거로** 오늘의 핵심을 2~3문장으로 쓰세요.
- 항목에 적힌 사실만 쓰세요. 점수·금액·날짜·인용 같은 숫자는 항목에 있는 것만 쓰고,
  항목에 없는 배경·원인·전망·결과를 덧붙이지 마세요.
- 항목 제목을 그대로 나열하지 말고, 큰 흐름과 항목 사이의 연결을 설명하세요.
- 문화예술은 [국내] 소식과 해외 소식을 나누어 설명하세요.
- 한국어로만 쓰세요(한자·일본어 금지). 외국 이름은 한글로 쓰세요.
- 입력된 카테고리를 모두 포함하고, 카테고리 이름은 그대로 쓰세요.
- 반드시 아래 JSON만 출력하세요 (설명, 코드펜스 없이):
{"overviews": {"카테고리 이름": "핵심 요약 2~3문장"}}"""
REFINE_BUDGET_SECONDS = 90
REFINE_REQUEST_SECONDS = 90
REFINE_DEADLINE = 600   # 실행 시작 후 이 시간(초)이 지났으면 2차 작업은 건너뛴다(워크플로 제한 대비)
_RUN_START = time.monotonic()


def refine_overviews(digest: dict, articles: list[Article], provider: str) -> dict:
    """2차 작업: 항목이 확정된 뒤, 그 항목들만 보고 카테고리별 '오늘의 핵심'을 다시 쓰게 한다.
    1차 응답의 핵심 요약은 항목에 없는 사실이 섞이는 일이 실측으로 확인되어(없는 경기 결과 등) 따로 한 번 더 쓰게 한다.
    실패하면 1차 결과를 그대로 쓴다(최선 노력)."""
    targets = [x for x in digest.get("sections", []) if not x.get("backfilled") and x.get("items")]
    if not targets or time.monotonic() - _RUN_START > REFINE_DEADLINE:
        return digest
    by_key = {_link_key(a.link): a for a in articles}
    blocks = []
    for sec in targets:
        lines = [f"## {sec['topic']}"]
        for it in sec["items"]:
            a = by_key.get(_link_key(str(it.get("link", ""))))
            lines.append(f"- [{a.region if a else ''}] {it.get('title', '')} – {it.get('summary', '')} ({it.get('source', '')})")
        blocks.append("\n".join(lines))
    user = "\n\n".join(blocks)
    topics = [x["topic"] for x in targets]

    def check(text: str) -> dict:
        ov = parse_json(text).get("overviews")
        if not isinstance(ov, dict):
            raise ValueError("overviews 없음")
        good = {str(t).strip(): v.strip() for t, v in ov.items() if isinstance(v, str) and len(v.strip()) >= 20}
        missing = [t for t in topics if t not in good]
        if len(missing) > len(topics) // 3:
            raise ValueError(f"핵심 요약이 빠진 카테고리가 많습니다: {missing}")
        return good

    global LAST_MODEL_USED
    keep_model = LAST_MODEL_USED
    try:
        if provider == "openrouter":
            text = _call_openrouter(REFINE_PROMPT, user, check, budget=REFINE_BUDGET_SECONDS,
                                    request_seconds=REFINE_REQUEST_SECONDS)
        else:
            text = {"anthropic": _call_anthropic, "gemini": _call_gemini}[provider](REFINE_PROMPT, user)
        good = check(text)
    except Exception as err:  # noqa: BLE001 - 2차 작업 실패는 치명적이지 않다
        print(f"[warn] 핵심 요약 재작성 실패, 1차 결과를 그대로 씁니다: {err}", file=sys.stderr)
        return digest
    finally:
        LAST_MODEL_USED = keep_model
    sections, changed = [], 0
    for sec in digest["sections"]:
        new = good.get(sec.get("topic", ""))
        if new and not sec.get("backfilled"):
            evidence = " ".join(f"{it.get('title', '')} {it.get('summary', '')}" for it in sec["items"])
            if _garbled(new) or _unsupported_numbers(new, evidence):
                print(f"[warn] {sec['topic']}: 재작성한 핵심 요약에 근거 없는 내용이 있어 쓰지 않습니다", file=sys.stderr)
            else:
                sec = {**sec, "overview": new}
                changed += 1
        sections.append(sec)
    print(f"핵심 요약 재작성: {changed}/{len(targets)}개 카테고리 반영")
    return {**digest, "sections": sections}


def summarize(articles: list[Article], provider: str) -> dict:
    global LAST_MODEL_USED
    LAST_MODEL_USED = ""
    lines = [
        f"[{i}] ({a.region}|{a.outlet}|{a.category}) {a.title} | {a.summary} | {a.link}"
        for i, a in enumerate(articles, 1)
    ]
    user = "\n".join(lines)

    def check(text: str) -> dict:
        return validate_digest(parse_json(text), articles)

    if provider == "openrouter":  # 무료 모델은 품질 편차가 커서, 검증에 실패하면 다음 모델로 넘어가도록 검사 함수를 넘김
        text = _call_openrouter(SYSTEM_PROMPT, user, check)
    else:
        text = {"anthropic": _call_anthropic, "gemini": _call_gemini}[provider](SYSTEM_PROMPT, user)
        LAST_MODEL_USED = {"anthropic": os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"),
                           "gemini": os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")}[provider]
    digest = validate_digest(parse_json(text), articles, verbose=True)
    digest = backfill_missing_categories(digest, articles)
    digest = ensure_domestic_art(digest, articles)
    digest = refine_overviews(digest, articles, provider)
    return {**digest, "model": LAST_MODEL_USED or provider}


def parse_json(text: str) -> dict:
    """응답에서 첫 번째 JSON 객체를 읽는다. 앞의 설명이나 ```json 코드펜스, 뒤에 붙은 군더더기(두 번째 객체·설명)는 무시."""
    start = text.find("{")
    if start == -1:
        raise ValueError(f"JSON을 찾을 수 없습니다: {text[:200]}")
    obj, _ = json.JSONDecoder().raw_decode(text, start)
    if not isinstance(obj, dict):
        raise ValueError("JSON 객체가 아닙니다")
    return obj


def topic_score(cat: str, a: Article) -> int:
    """해당 카테고리와 얼마나 관련 있는 기사인지 점수 (0이면 무관)."""
    core, other = KEYWORDS[cat]
    text = f"{a.title} {a.summary}"
    return 3 * len({m.lower() for m in core.findall(text)}) + len({m.lower() for m in other.findall(text)})


def art_score(a: Article) -> int:
    return topic_score("문화예술", a)


def _reclassify(a: Article) -> Article:
    """헤드라인 모드 전용: 피드 카테고리가 부정확한 기사를 키워드로 바로잡는다.
    - 어느 피드에 있든 코인 핵심어가 있으면 '코인'
    - '종합' 피드 기사는 가장 관련 높은 카테고리로, 해당 없으면 '정치·사회'"""
    if a.category != "코인" and topic_score("코인", a) >= 3:
        return replace(a, category="코인")
    if a.category == "종합":
        best, score = "정치·사회", 2
        for cat in ("세계 이슈", "경제·증시", "문화예술"):
            sc = topic_score(cat, a)
            if sc > score:
                best, score = cat, sc
        return replace(a, category=best)
    return a


def _pick_scored(items: list[Article], cat: str, limit: int) -> list[Article]:
    """키워드 점수 순으로 고르되 한 신문사가 3건을 넘지 않게 한다. 문화예술은 국내 소식을 먼저 최대 3건 확보."""
    strict = cat in STRICT_CATEGORIES
    ranked = [a for a in sorted(items, key=lambda x: -topic_score(cat, x)) if topic_score(cat, a) > 0 or not strict]
    picked: list[Article] = []
    per_outlet: dict[str, int] = {}

    def take(a: Article) -> None:
        picked.append(a)
        per_outlet[a.outlet] = per_outlet.get(a.outlet, 0) + 1

    if cat == "문화예술":
        for a in [x for x in ranked if x.region == "국내"][:3]:
            take(a)
    for a in ranked:
        if len(picked) >= limit:
            break
        if a not in picked and per_outlet.get(a.outlet, 0) < 3:
            take(a)
    # 정렬은 '점수 순'이 아니라 읽기 좋게 원래 수집 순서(신문사 섞임)로 되돌림
    order = {id(a): i for i, a in enumerate(items)}
    return sorted(picked, key=lambda a: order[id(a)])


def headlines_only(articles: list[Article], headline: str = "AI 요약 없이 헤드라인만 제공합니다") -> dict:
    """AI 없이(비용 0원) 카테고리별 헤드라인만 묶는 모드. 카테고리별 비중은 CATEGORY_LIMITS를 따르고,
    세계 이슈·경제·코인·문화예술은 키워드로 관련 기사를 우선 고른다."""
    by_cat: dict[str, list[Article]] = {}
    for a in map(_reclassify, articles):
        by_cat.setdefault(a.category, []).append(a)
    sections = []
    for cat in CATEGORIES + [c for c in by_cat if c not in CATEGORIES]:
        items = by_cat.get(cat)
        if not items:
            continue
        limit = CATEGORY_LIMITS.get(cat, 4)
        if cat in KEYWORDS:
            picked = _pick_scored(items, cat, limit)
        else:  # 정치·사회, IT·과학, 스포츠: 신문사가 고르게 섞이도록 번갈아 채택
            picked, queues = [], {}
            for a in items:
                queues.setdefault(a.outlet, []).append(a)
            lists = list(queues.values())
            for rank in range(max(len(x) for x in lists)):
                for lst in lists:
                    if rank < len(lst) and len(picked) < limit:
                        picked.append(lst[rank])
        if picked:
            sections.append({"topic": cat, "items": [
                {"title": html.unescape(a.title), "summary": _clip(a.summary, 120), "source": a.outlet, "link": a.link}
                for a in picked]})
    return {"headline": headline, "sections": sections, "ai": False}


def outlets_by_region(articles: list[Article]) -> dict[str, list[str]]:
    """실제로 기사를 가져온 신문사 목록 (지역별, 입력 순서 유지)."""
    out: dict[str, list[str]] = {}
    for a in articles:
        names = out.setdefault(a.region or "기타", [])
        if a.outlet not in names:
            names.append(a.outlet)
    return out


# ---------- 렌더링 ----------

def _safe_url(url: str) -> str:
    return url if url.startswith(("http://", "https://")) else "#"


def _footer(digest: dict) -> str:
    if digest.get("ai", True):
        return "AI가 자동 요약한 내용이므로 중요한 사항은 원문을 확인하세요."
    return "AI 요약 없이 각 신문사의 제목과 발췌문을 모은 목록입니다. 자세한 내용은 원문을 확인하세요."


def _meta_line(digest: dict) -> str:
    """발송 하단의 실행 정보(몇 건·어느 모델·읽지 못한 매체). 문제가 생겼을 때 원인을 바로 알 수 있게 한다."""
    meta = digest.get("meta") or {}
    if not meta:
        return ""
    parts = [f"기사 {meta.get('articles', 0)}건", f"매체 {meta.get('outlets', 0)}곳"]
    if digest.get("ai", True):
        parts.append("요약 모델: " + (str(digest.get("model") or "").replace(":free", "") or "알 수 없음"))
    else:
        parts.append("AI 요약 없음")
    failed = meta.get("failed_feeds") or []
    if failed:
        parts.append("읽지 못한 매체: " + ", ".join(failed))
    return " · ".join(parts)


def _message_line(digest: dict) -> tuple[str, str]:
    m = digest.get("message") or {}
    return (m.get("ko", ""), m.get("en", ""))


def _overviews(digest: dict) -> list[tuple[str, str]]:
    """카테고리별 핵심 요약(overview) 목록. AI 요약이 없는 헤드라인 모드에서는 비어 있다."""
    return [(s.get("topic", ""), s["overview"].strip())
            for s in digest.get("sections", []) if (s.get("overview") or "").strip()]


def render_html(digest: dict, date: datetime) -> str:
    e = html.escape
    parts = [
        '<div style="max-width:640px;margin:0 auto;font-family:-apple-system,'
        "'Apple SD Gothic Neo','Malgun Gothic',sans-serif;color:#222;line-height:1.6\">",
        f'<h1 style="font-size:20px;margin:0 0 4px">📰 {date.year}년 {date.month}월 {date.day}일 뉴스 브리핑</h1>',
        f'<p style="margin:0 0 20px;color:#555">{e(digest.get("headline", ""))}</p>',
    ]
    weather = _weather_lines(digest)
    if weather:
        parts.append('<div style="background:#eef6ff;border-radius:8px;padding:12px 16px;margin:0 0 8px">'
                     '<div style="font-weight:700;margin-bottom:4px">🌤 오늘의 날씨</div>')
        parts.extend(f'<p style="margin:4px 0;font-size:14px">{e(x)}</p>' for x in weather)
        parts.append("</div>")
    ko, en = _message_line(digest)
    if ko:
        parts.append('<div style="background:#fff8e6;border-radius:8px;padding:12px 16px;margin:0 0 8px">'
                     '<div style="font-weight:700;margin-bottom:4px">☀️ 오늘의 한마디</div>'
                     f'<p style="margin:4px 0;font-size:15px">{e(ko)}</p>'
                     f'<p style="margin:4px 0;font-size:14px;color:#555">{e(en)}</p></div>')
    overviews = _overviews(digest)
    if overviews:  # 최상단: 카테고리별 오늘의 핵심
        parts.append('<div style="background:#f4f6fa;border-radius:8px;padding:14px 16px;margin:0 0 8px;color:#222">'
                     '<div style="font-weight:700;margin-bottom:4px">📌 카테고리별 오늘의 핵심</div>')
        parts.extend(f'<p style="margin:8px 0;font-size:14px"><b>{e(t)}</b> · {e(o)}</p>' for t, o in overviews)
        parts.append("</div>")
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
    outlets = digest.get("outlets") or {}
    if outlets:
        parts.append('<div style="font-size:12px;color:#666;margin-top:28px;border-top:1px solid #ddd;padding-top:10px">'
                     "<b>참고한 신문사</b><br>")
        parts.extend(f"{e(region)}: {e(', '.join(names))}<br>" for region, names in outlets.items())
        parts.append("</div>")
    meta = _meta_line(digest)
    parts.append(
        '<p style="font-size:11px;color:#aaa;margin-top:16px">'
        f"{e(_footer(digest))}" + (f"<br>{e(meta)}" if meta else "") + "</p></div>"
    )
    return "".join(parts)


def render_text(digest: dict) -> str:
    out = [digest.get("headline", ""), ""]
    weather = _weather_lines(digest)
    if weather:
        out.append("[오늘의 날씨]")
        out.extend(f"- {x}" for x in weather)
        out.append("")
    ko, en = _message_line(digest)
    if ko:
        out.extend(["[오늘의 한마디]", ko, en, ""])
    overviews = _overviews(digest)
    if overviews:
        out.append("[카테고리별 오늘의 핵심]")
        out.extend(f"- {t}: {o}" for t, o in overviews)
        out.append("")
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
    blocks = [f"📰 <b>{date.year}년 {date.month}월 {date.day}일 뉴스 브리핑</b>\n{e(digest.get('headline', ''))}"]
    weather = _weather_lines(digest)
    if weather:
        blocks.append("🌤 <b>오늘의 날씨</b>\n" + "\n".join(e(x) for x in weather))
    ko, en = _message_line(digest)
    if ko:
        blocks.append(f"☀️ <b>오늘의 한마디</b>\n{e(ko)}\n<i>{e(en)}</i>")
    overviews = _overviews(digest)
    if overviews:
        blocks.append("📌 <b>카테고리별 오늘의 핵심</b>\n" + "\n".join(
            f"<b>{e(t)}</b> · {e(o)}" for t, o in overviews))
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


ISSUE_BODY_LIMIT = 60000  # GitHub 이슈 본문 한도는 65,536자


def _md(text: str) -> str:
    """마크다운 특수문자를 무력화하고, @멘션이 엉뚱한 사람에게 알림을 보내지 않게 한다."""
    import re
    text = text.replace("@", "@​")
    return re.sub(r"([\\`*_\[\]<>|~#])", r"\\\1", text)


def render_markdown(digest: dict, date: datetime) -> str:
    """GitHub 이슈 본문(마크다운). 이슈가 올라오면 GitHub가 알림 메일을 보내준다."""
    out = [f"**{_md(digest.get('headline', ''))}**", ""]
    weather = _weather_lines(digest)
    if weather:
        out.append("## 🌤 오늘의 날씨")
        out.extend(f"- {_md(x)}" for x in weather)
        out.append("")
    ko, en = _message_line(digest)
    if ko:
        out.extend(["## ☀️ 오늘의 한마디", f"> {_md(ko)}  ", f"> _{_md(en)}_", ""])
    overviews = _overviews(digest)
    if overviews:
        out.append("## 📌 카테고리별 오늘의 핵심")
        out.extend(f"- **{_md(t)}** · {_md(o)}" for t, o in overviews)
        out.extend(["", "---", ""])
    for sec in digest.get("sections", []):
        out.append(f"### {_md(sec.get('topic', ''))}")
        for it in sec.get("items", []):
            url = _safe_url(it.get("link", "")).replace(")", "%29").replace(" ", "%20")
            out.append(f"- **[{_md(it.get('title', ''))}]({url})**  \n"
                       f"  {_md(it.get('summary', ''))} _({_md(it.get('source', ''))})_")
        out.append("")
    outlets = digest.get("outlets") or {}
    if outlets:
        out.append("---")
        out.append("**참고한 신문사**  ")
        out.extend(f"{_md(region)}: {_md(', '.join(names))}  " for region, names in outlets.items())
    out.append("")
    out.append(f"_{_md(_footer(digest))}_")
    meta = _meta_line(digest)
    if meta:
        out.append(f"  \n_{_md(meta)}_")
    return "\n".join(out)[:ISSUE_BODY_LIMIT]


def send_github_issue(title: str, body: str) -> None:
    """저장소에 이슈를 하나 만든다. 이슈 담당자(기본: 저장소 주인)에게 GitHub가 메일로 알려준다.
    GitHub Actions에서는 별도의 키 없이 자동 제공되는 GITHUB_TOKEN으로 동작한다."""
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    who = os.environ.get("ISSUE_ASSIGNEES") or os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    assignees = [x.strip() for x in who.split(",") if x.strip()]

    def post(payload: dict) -> None:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/issues",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "Content-Type": "application/json",
                     "User-Agent": "news-digest"})
        with urllib.request.urlopen(req, timeout=30):
            pass

    payload = {"title": title, "body": body}
    if assignees:
        payload["assignees"] = assignees
    try:
        post(payload)
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:300]
        if err.code == 422 and assignees:  # 담당자로 지정할 수 없는 계정(조직 등)이면 담당자 없이 재시도
            payload.pop("assignees")
            try:
                post(payload)
                return
            except urllib.error.HTTPError as err2:
                err, detail = err2, err2.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"GitHub 이슈 생성 실패 (HTTP {err.code}): {detail}") from None


def configured_channels() -> list[str]:
    channels = []
    if all(os.environ.get(k) for k in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO")):
        channels.append("email")
    if all(os.environ.get(k) for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")):
        channels.append("telegram")
    # GitHub 알림: Actions 안에서만 가능. 이메일/텔레그램이 하나도 없으면 자동으로 켜지고,
    # 다른 채널과 함께 쓰려면 ISSUE_NOTIFY=true, 끄려면 ISSUE_NOTIFY=false
    in_actions = all(os.environ.get(k) for k in ("GITHUB_ACTIONS", "GITHUB_TOKEN", "GITHUB_REPOSITORY"))
    flag = os.environ.get("ISSUE_NOTIFY", "").strip().lower()
    if in_actions and (flag in ("1", "true", "yes") or (not channels and flag not in ("0", "false", "no"))):
        channels.append("github")
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

    chain = [] if args.no_llm else provider_chain()
    if not chain:
        digest = headlines_only(articles)
    else:
        digest, last_err = None, None
        for provider in chain:  # 앞 공급자가 실패하면(한도·키·무료 티어 불가 등) 다음 공급자로
            try:
                digest = summarize(articles, provider)
                print(f"AI 요약 완료: {provider}")
                break
            except Exception as err:
                last_err = err
                print(f"[warn] {provider} 요약 실패: {err}", file=sys.stderr)
        if digest is None:  # 모두 실패해도 오늘 메일은 보낸다
            print("[warn] 모든 AI 공급자가 실패해 헤드라인만 발송합니다", file=sys.stderr)
            if isinstance(last_err, ModelUnavailable):
                note = MODEL_NOTE
            elif isinstance(last_err, QuotaExceeded) or type(last_err).__name__ == "RateLimitError":
                note = QUOTA_NOTE
            elif isinstance(last_err, FreeTierUnavailable):
                note = NO_FREE_NOTE
            else:
                note = FAIL_NOTE
            digest = headlines_only(articles, headline=note)

    digest["outlets"] = outlets_by_region(articles)
    now = datetime.now(KST)
    digest["weather"] = fetch_weather()
    digest["message"] = daily_message(now)
    digest["meta"] = {"articles": len(articles), "outlets": sum(len(v) for v in digest["outlets"].values()),
                      "failed_feeds": list(dict.fromkeys(FEED_FAILURES))}
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
        print("발송 채널이 설정되지 않았습니다. GitHub Actions에서 실행하면 GitHub 알림이 자동으로 쓰이고, "
              "로컬에서는 이메일(SMTP_*, MAIL_TO) 또는 텔레그램(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) "
              "환경변수를 설정하세요.", file=sys.stderr)
        return 2

    failed = False
    for ch in channels:  # 한 채널이 실패해도 나머지는 계속 시도
        try:
            if ch == "email":
                send_email(subject, html_body, text_body)
            elif ch == "telegram":
                send_telegram(render_telegram(digest, now))
            else:
                send_github_issue(subject, render_markdown(digest, now))
            print(f"발송 완료: {ch}")
        except Exception as err:
            failed = True
            print(f"[error] {ch} 발송 실패: {err}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
