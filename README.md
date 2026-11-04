# 📰 Daily News Digest

국내·미국·영국 등 주요 신문사의 RSS를 모아 **카테고리별로 정리**하고, 매일 아침 **이메일 및/또는 텔레그램**으로 보내줍니다.
GitHub Actions로 돌아가므로 내 컴퓨터나 서버가 필요 없습니다.

## 💰 비용 — 0원으로 운영하기

| 구성요소 | 비용 | 비고 |
|---|---|---|
| GitHub Actions (실행) | 무료 | 비공개 저장소는 월 2,000분 무료, 공개 저장소는 무제한 무료. 이 작업은 하루 1분 안팎(월 30분 내외). 무료 한도를 넘어도 기본 지출 한도가 0달러라 과금되지 않음 |
| 이메일 (Gmail SMTP) | 무료 | 앱 비밀번호 사용 |
| 텔레그램 봇 | 무료 | |
| **요약 엔진** | 선택 | 아래 3가지 중 택 1 |

**요약 엔진 선택**

1. **없음 (0원, 기본값)** — `ANTHROPIC_API_KEY`/`GEMINI_API_KEY`를 설정하지 않으면 AI 없이 카테고리별 헤드라인만 보냅니다. 해외 기사는 영어 원문 제목 그대로입니다.
2. **Google Gemini 무료 티어 (0원, 한국어 요약·번역 포함)** — [Google AI Studio](https://aistudio.google.com/apikey)에서 키를 발급해 `GEMINI_API_KEY`로 등록. 무료 티어의 분당·일일 한도는 계정별로 AI Studio에서 확인해야 하고 바뀔 수 있으며, 무료 티어에 보낸 내용은 Google이 제품 개선에 사용할 수 있습니다(뉴스 제목·요약뿐이라 민감 정보는 없음).
3. **Claude API (유료, 종량제)** — `ANTHROPIC_API_KEY` 등록. **Claude.ai 구독(Pro/Max)과는 별개 상품·별개 결제**입니다. [console.anthropic.com](https://console.anthropic.com)에서 크레딧을 충전해야 하며, 구독을 해지해도 API는 영향이 없지만 구독이 API를 대신해 주지도 않습니다.

> AI 호출이 실패하면(한도 초과·키 만료 등) 메일이 끊기지 않도록 **헤드라인만으로 대체해 발송**하고, 메일 상단에 실패 사실을 표시합니다.

### Claude 구독을 끊어도 계속 오나요?
네. 이 시스템은 GitHub에서 독립적으로 돌고 Claude 구독과 무관합니다. 단, **코드가 GitHub 저장소에 올라가 있어야** 하고, 요약 엔진은 위 1·2번이면 0원, 3번이면 API 크레딧이 필요합니다.

### ⚠️ 60일 규칙 (공개 저장소만 해당)
GitHub는 **공개 저장소**에서 60일간 활동(푸시 등)이 없으면 예약 실행을 자동 중지합니다([공식 문서](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)). **비공개(Private) 저장소로 만들면 이 문제가 없고** 월 2,000분 무료로 충분합니다. 공개로 둘 거라면 두 달에 한 번 아무 커밋이나 올리거나 Actions 탭에서 워크플로를 다시 켜 주세요.

## ✅ 가장 쉬운 방법: GitHub 알림 (입력할 값 0개)

이메일·텔레그램 설정을 **하나도 하지 않으면**, 실행될 때마다 이 저장소에 **이슈(글) 하나**로 뉴스를 올리고 GitHub가 저장소 주인에게 **알림 메일**을 보냅니다. 비밀번호나 키를 넣을 필요가 없습니다.

1. 저장소 → **Actions** → **Daily News Digest** → **Run workflow**
2. 1~2분 뒤 **Issues** 탭에 글이 올라오고, GitHub 계정의 이메일로 알림이 옵니다 (보낸 사람: GitHub).

메일이 안 오면: GitHub 우측 상단 프로필 → Settings → Notifications에서 이메일 알림이 켜져 있는지 확인하고, 저장소 상단 **Watch** → *All Activity*로 바꿔 보세요.

한계: 보낸 사람이 GitHub이고 서식이 단순하며, **GitHub 계정에 등록된 이메일로만** 받습니다. 다른 사람이 받으려면 그 사람도 GitHub 계정이 있어야 하고 저장소에 접근할 수 있어야 합니다(`ISSUE_ASSIGNEES` 변수에 사용자명을 쉼표로 적으면 담당자로 지정되어 알림이 갑니다). 하루에 이슈가 1개씩 쌓입니다.
다른 방식(이메일·텔레그램)을 하나라도 설정하면 GitHub 알림은 자동으로 꺼지며, 함께 쓰려면 변수 `ISSUE_NOTIFY`를 `true`로 두세요.

## 설정 (이메일/텔레그램을 쓰고 싶을 때)

1. 이 코드를 **비공개 GitHub 저장소**에 올립니다 (기본 브랜치에 있어야 스케줄이 동작).
2. 저장소 → Settings → Secrets and variables → Actions → **Secrets**에 필요한 것만 등록:

| Secret | 값 | 필수 |
|---|---|---|
| `GEMINI_API_KEY` | Gemini 키 (무료 요약) | 선택 |
| `ANTHROPIC_API_KEY` | Claude API 키 (유료 요약) | 선택 |
| `SMTP_USER` / `SMTP_PASSWORD` / `MAIL_TO` | Gmail 주소 / [앱 비밀번호](https://myaccount.google.com/apppasswords) / 수신 주소(쉼표로 여러 명) | 이메일을 쓸 때 |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 아래 참고 | 텔레그램을 쓸 때 |

값이 설정된 채널로만 발송됩니다 (이메일만 / 텔레그램만 / 둘 다).
3. Actions 탭 → **Daily News Digest** → *Run workflow*로 수동 테스트.

기본 발송 시각은 매일 07:30 KST(`.github/workflows/daily-news.yml`의 cron 수정). GitHub 스케줄은 수 분~수십 분 늦을 수 있습니다.

### 텔레그램 설정
1. 텔레그램에서 **@BotFather** → `/newbot` → **토큰** 받기
2. 만든 봇에게 `/start` 보내기
3. 브라우저에서 `https://api.telegram.org/bot<토큰>/getUpdates` → `"chat":{"id":123456789,...}`의 숫자가 **채팅 ID** (그룹·채널은 음수)

## 참고하는 신문사 / 카테고리

| 구분 | 신문사 |
|---|---|
| 국내 (8) | 연합뉴스, 조선일보, 한겨레, 경향신문, 한국경제, 매일경제, 오마이뉴스, 전자신문 |
| 미국 (14) | NYT, Bloomberg, CBS News, NBC News, ABC News, Fox News, The Hill, Politico, LA Times, Axios, TechCrunch, The Verge, Wired, Ars Technica |
| 영국 (7) | BBC, The Guardian, Financial Times, Sky News, The Independent, Daily Mail, New Scientist |
| 기타 해외 (5) | Al Jazeera, DW, Japan Times, SCMP, Nikkei Asia |

**카테고리 (고정 순서)**: 정치 · 경제 · 사회 · 국제 · IT·과학 · 문화·스포츠
(AI 요약 시) 같은 사건을 여러 신문사가 다루면 하나로 묶고 보도한 신문사를 함께 표시합니다. 메일 하단에는 그날 실제로 수집된 신문사가 지역별로 나옵니다.

제외한 곳: 중앙일보(RSS 중단), WSJ·CNN(갱신 중단), The Economist(주간), 동아일보(응답 없음), 한국일보·서울신문·NPR·Washington Post·USA Today·CNBC(접근 불가), The Telegraph(유료 차단), The Times(RSS 없음).
조선일보 RSS는 연예·스포츠·일본어판 기사가 많이 섞여 있어 품질에 한계가 있습니다. RSS 주소는 언제든 바뀔 수 있으니 한동안 안 오는 신문사가 있으면 `feeds.json`을 점검하세요.

`samples/2026-11-04.html`은 이전 구성(국내 8·해외 12곳)으로 만든 샘플 메일입니다 (API 키 없이 수집한 기사를 직접 요약한 예시).

## 뉴스 소스 바꾸기

`feeds.json`의 `feeds`에 `{ "outlet": "신문사", "region": "국내|미국|영국|기타 해외", "category": "정치|경제|사회|국제|IT·과학|문화·스포츠|종합", "url": "RSS 주소" }`를 추가/삭제하세요. `category`는 힌트이며 AI가 내용에 맞게 최종 분류합니다. `max_total_articles`(기본 350)는 AI에 보내는 기사 수 상한입니다.

## 로컬 실행

```bash
pip install -r requirements.txt            # (Claude 사용 시 pip install anthropic 추가)
python news_digest.py --no-llm --dry-run   # 키·메일 없이 수집+HTML 생성 (비용 0원)
python news_digest.py --dry-run            # AI 요약까지 (digest.html로 저장)
python news_digest.py                      # 실제 발송 (설정된 채널 전부)
pytest
```
