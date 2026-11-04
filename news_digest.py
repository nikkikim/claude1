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

    def _parse(feed: dict):
        outlet = feed.get("outlet") or feed.get("name", "")
        try:
            parsed = feedparser.parse(feed["url"], agent="news-digest/1.0")
        except Exception as e:  # 한 피드가 죽어도 전체는 계속
            print(f"[warn] {outlet}: {e}", file=sys.stderr)
            return None
        if parsed.get("bozo") and not parsed.entries:
            print(f"[warn] {outlet}: 피드를 읽지 못했습니다", file=sys.stderr)
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
                    summary=_clip(_clean_summary(_strip_html(entry.get("summary", ""))), 200),
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


def _clean_summary(text: str) -> str:
    """연합·뉴시스 등의 기사 앞머리 '(서울=연합뉴스) 홍길동 기자 =' 같은 바이라인을 제거하고 공백을 정리한다."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[\(\[][^\)\]]{1,40}[\)\]]\s*", "", text)                       # (서울=연합뉴스) / [서울=뉴시스]
    text = re.sub(r"^(?:[가-힣A-Za-z· ]{2,25}\s)?[가-힣]{2,4}(?:\s[가-힣]{2,8})?\s?(?:기자|특파원)\s*=\s*", "", text)  # 홍길동 (미술전문) 기자 =
    return text.strip()


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n].rstrip() + "…"


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

규칙:
- 카테고리는 다음 순서로 고정: {", ".join(CATEGORIES)}. 해당 기사가 없는 카테고리는 생략.
  '카테고리힌트'는 참고만 하고, 내용에 맞게 직접 분류하세요('종합'은 직접 판단).
- 카테고리별 항목 수 상한: {", ".join(f"{c} {n}개" for c, n in CATEGORY_LIMITS.items())}. 중요한 기사가 부족하면 적게 담고,
  정치·사회/IT·과학/스포츠는 짧게 유지하세요. 전체 25~35개.
- 같은 사건을 여러 신문사가 다뤘으면 하나로 묶고, source에 보도한 신문사를 모두(최대 3곳) 적으세요.
  국내·미국·영국 등 여러 나라 매체를 골고루 반영하고, 시각 차이가 있으면 summary에 한 문장으로 덧붙이세요.
- 각 항목 summary는 1~2문장. 사실 위주로, 과장·추측 금지.
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


class FreeTierUnavailable(RuntimeError):
    """이 키가 속한 Google 프로젝트에는 Gemini 무료 티어가 제공되지 않는다(HTTP 403)."""


NO_FREE_NOTE = "이 키의 Google 프로젝트에서는 Gemini 무료 티어를 쓸 수 없어 헤드라인만 제공합니다 (새 프로젝트에서 키를 다시 발급해 보세요)"
QUOTA_NOTE = "무료 사용 한도를 초과해 오늘은 헤드라인만 제공합니다 (한도가 다시 채워지면 다음 발송부터 자동으로 요약이 돌아옵니다)"
FAIL_NOTE = "AI 요약에 실패해 헤드라인만 제공합니다 (키/모델 설정을 확인하세요)"


def _call_gemini(system: str, user: str) -> str:
    model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "maxOutputTokens": 12000, "temperature": 0.2},
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
# OPENROUTER_MODELS(쉼표 구분)로 바꿀 수 있다. 마지막의 openrouter/free는 그때그때 가능한 무료 모델로 자동 연결해 주는 라우터.
OPENROUTER_DEFAULT_MODELS = ("google/gemma-4-31b-it:free", "nvidia/nemotron-3-ultra-550b-a55b:free", "openrouter/free")
OPENROUTER_BUDGET_SECONDS = 420  # 무료 모델은 느릴 수 있어 전체 시도 시간을 제한(워크플로 제한 10분 이내)


def _call_openrouter(system: str, user: str) -> str:
    key = os.environ["OPENROUTER_API_KEY"]
    models = [m.strip() for m in os.environ.get("OPENROUTER_MODELS", "").split(",") if m.strip()] \
        or list(OPENROUTER_DEFAULT_MODELS)
    start = time.monotonic()
    last: Exception | None = None
    for model in models:
        if time.monotonic() - start > OPENROUTER_BUDGET_SECONDS:
            break
        body = json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2, "max_tokens": 12000,
        }).encode()
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com", "X-OpenRouter-Title": "news-digest"})  # 키는 헤더로만 전송
        try:
            with urllib.request.urlopen(req, timeout=150) as r:
                data = json.load(r)
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:300]
            exc = QuotaExceeded if err.code == 429 else RuntimeError
            last = exc(f"OpenRouter 오류 ({model}, HTTP {err.code}): {detail}")
            if err.code in (401, 402, 403):  # 키/권한 문제는 다른 모델로 바꿔도 소용없음
                raise last from None
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            last = RuntimeError(f"OpenRouter 연결 실패 ({model}): {err}")
            continue
        try:
            text = (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            text = ""
        if not text:  # 200이어도 본문에 error만 오거나 비어 있는 경우
            last = RuntimeError(f"OpenRouter 빈 응답 ({model}): {str(data)[:200]}")
            continue
        try:
            if not parse_json(text).get("sections"):
                raise ValueError("sections 없음")
        except ValueError as err:  # 형식을 못 맞추는 모델이면 다음 모델로
            last = RuntimeError(f"OpenRouter 응답 형식 오류 ({model}): {err}")
            continue
        print(f"OpenRouter 모델 사용: {model}")
        return text
    raise last or RuntimeError("OpenRouter 호출에 실패했습니다")


def summarize(articles: list[Article], provider: str) -> dict:
    lines = [
        f"[{i}] ({a.region}|{a.outlet}|{a.category}) {a.title} | {a.summary} | {a.link}"
        for i, a in enumerate(articles, 1)
    ]
    call = {"anthropic": _call_anthropic, "gemini": _call_gemini, "openrouter": _call_openrouter}[provider]
    return parse_json(call(SYSTEM_PROMPT, "\n".join(lines)))


def parse_json(text: str) -> dict:
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"JSON을 찾을 수 없습니다: {text[:200]}")
    return json.loads(text[start:end + 1])


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
    parts.append(
        '<p style="font-size:11px;color:#aaa;margin-top:16px">'
        f"{_footer(digest)}</p></div>"
    )
    return "".join(parts)


def render_text(digest: dict) -> str:
    out = [digest.get("headline", ""), ""]
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
    out.append(f"_{_footer(digest)}_")
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
            if isinstance(last_err, QuotaExceeded) or type(last_err).__name__ == "RateLimitError":
                note = QUOTA_NOTE
            elif isinstance(last_err, FreeTierUnavailable):
                note = NO_FREE_NOTE
            else:
                note = FAIL_NOTE
            digest = headlines_only(articles, headline=note)

    digest["outlets"] = outlets_by_region(articles)
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
