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

**요약 엔진 선택** (키를 여러 개 등록하면 claude → gemini → openrouter 순으로 시도하고, 앞이 실패하면 다음으로 자동 전환합니다)

1. **없음 (0원, 기본값)** — 키를 하나도 등록하지 않으면 AI 없이 카테고리별 헤드라인만 보냅니다. 해외 기사는 영어 원문 제목 그대로입니다.
2. **OpenRouter 무료 모델 (0원 가능, 한국어 요약 포함)** — [openrouter.ai](https://openrouter.ai)에서 키를 발급해 `OPENROUTER_API_KEY`로 등록. 무료(`:free`) 모델은 공식 문서상 분당 20회, **하루 50회**까지(누적 10크레딧 이상 구매 시 1,000회)라 하루 1회 호출에는 충분합니다. 무료 모델 목록은 수시로 바뀌어서 위에서부터 차례로 시도하며(`OPENROUTER_MODELS` 변수로 변경 가능), 한국어 품질과 JSON 형식 준수는 모델마다 다를 수 있습니다. 카드 등록이 필요한지는 문서에 명시돼 있지 않습니다.
3. **Google Gemini** — [AI Studio](https://aistudio.google.com/apikey)에서 키 발급 후 `GEMINI_API_KEY`. 단, 무료 티어는 **Google Cloud 프로젝트 단위로 자격이 평가**되어 일부 프로젝트/계정에서는 `403 free tier is not available for this project`로 쓸 수 없고(같은 프로젝트에서 키만 다시 만들어도 해결되지 않음), 그 경우 유료 결제 연결이 필요합니다.
4. **Claude API (유료, 종량제)** — `ANTHROPIC_API_KEY` 등록. **Claude.ai 구독(Pro/Max)과는 별개 상품·별개 결제**입니다. [console.anthropic.com](https://console.anthropic.com)에서 크레딧을 충전해야 하며, 구독을 해지해도 API는 영향이 없지만 구독이 API를 대신해 주지도 않습니다.

무료로 쓸 수 없는 것: **Hugging Face**(무료 계정은 Inference Providers 월 크레딧 없음, 크레딧 구매 또는 PRO 구독 필요), **GitHub Models**(2026-07-30 서비스 종료), **Cerebras**(무료 체험이 결제수단 등록을 요구하고 가입 시 $5 크레딧 1회 지급).
조사했지만 보류한 것: **Groq**(무료 요금제 한도가 분당 8K 토큰 수준으로 알려져 있어 기사를 여러 번 쪼개 보내야 함), **Cloudflare Workers AI**(하루 10,000 뉴런 무료이나 계정 ID+토큰 두 가지 설정이 필요).

> AI 호출이 실패하면(한도 초과·키 만료 등) 메일이 끊기지 않도록 **헤드라인만으로 대체해 발송**하고, 메일 상단에 실패 사실을 표시합니다.

### Gemini 키 발급 방법 (한국어 요약 + 카테고리별 핵심 요약에 필요)
1. https://aistudio.google.com/apikey 에 Google 계정으로 로그인합니다.
2. 처음이면 약관 동의 창이 뜹니다. 동의하면 기본 프로젝트가 자동으로 만들어집니다.
3. **Create API key**(API 키 만들기)를 눌러 키를 만들고 복사합니다. 키는 비밀번호처럼 다루세요.
4. GitHub 저장소 → Settings → Secrets and variables → Actions → **New repository secret**
   → Name: `GEMINI_API_KEY`, Secret: 복사한 키 → **Add secret**
5. Actions → Daily News Digest → Run workflow로 실행해 이슈 맨 위에 "📌 카테고리별 오늘의 핵심"이 나오는지 확인합니다.

문제가 생기면: 이슈 제목이 "AI 요약에 실패해 헤드라인만 제공합니다"이면 Actions 실행 로그의 *Send digest* 단계에서 `Gemini API 오류 (HTTP …)`를 확인하세요.
`429`는 무료 한도 초과(한도가 다시 채워지면 다음 발송부터 자동으로 요약이 돌아오며, 그 사이에는 헤드라인만 발송), `403 ... free tier is not available for this project`는 이 키가 속한 Google 프로젝트에 무료 티어가 없다는 뜻(AI Studio에서 새 프로젝트로 키를 다시 발급), 그 밖의 `400/403`은 키 오류, `404`는 모델 이름 문제입니다. 404면 저장소 Settings → Secrets and variables → Actions → **Variables** 탭에서 `GEMINI_MODEL`을 `gemini-3.6-flash` 등 다른 무료 모델로 지정하세요.

### OpenRouter 키 발급 방법
1. https://openrouter.ai 에 접속해 로그인(가입)합니다.
2. 계정 메뉴에서 **Keys**(API 키) 화면으로 가서 새 키를 만들고 복사합니다. 키는 비밀번호처럼 다루세요.
3. GitHub 저장소 → Settings → Secrets and variables → Actions → **New repository secret** → Name: `OPENROUTER_API_KEY`, Secret: 복사한 키.
4. Actions → Daily News Digest → Run workflow로 실행합니다. 로그의 *Send digest* 단계에 `AI 요약 완료: openrouter`와 `OpenRouter 모델 사용: …`이 찍히면 성공입니다.

실패하면 로그에서 `OpenRouter 오류 (모델, HTTP …)`를 확인하세요. `401`은 키 오류, `429`는 무료 한도 초과(하루 50회), 그 밖의 오류는 다음 무료 모델로 자동 넘어갑니다.

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

독자 관심사에 맞춰 **세계 이슈 · 경제·증시 · 코인 · 문화예술**에 비중을 둡니다. 카테고리 순서가 곧 우선순위이고, 괄호는 하루 최대 항목 수입니다.
**세계 이슈(7) → 경제·증시(7) → 코인(4) → 문화예술(8) → 정치·사회(4) → IT·과학(3) → 스포츠(2)**

| 영역 | 매체 |
|---|---|
| 세계 이슈 (전쟁·국가 간 관계) | 연합뉴스 국제·북한, BBC, NYT, The Guardian, Al Jazeera, DW, Euronews, CNA, Kyiv Independent, The Diplomat, Foreign Policy, Al-Monitor, Middle East Eye, Japan Times, SCMP, Korea Times, Yonhap English |
| 경제·증시 | 한국경제·매일경제 증권면, 머니투데이, 연합뉴스, 한겨레, 경향신문, Bloomberg, MarketWatch, Investing.com, Financial Times, NYT·BBC·Guardian 경제면, Nikkei Asia |
| 코인 | CoinDesk, Cointelegraph, Decrypt, The Block, Bitcoin Magazine, 블록미디어, 토큰포스트 |
| 문화예술 (해외) | ARTnews, Artforum, Hyperallergic, Artnet News, Artsy, Colossal, ArtAsiaPacific, Dezeen, Designboom, ArchDaily, NYT Art & Design·Arts, Guardian Art·Stage·Books, BBC Arts |
| 문화예술 (국내) | 연합뉴스 문화, 뉴시스 문화, 매일경제 문화, 한국경제 라이프, 한겨레 문화, 경향신문 문화 |
| 정치·사회·IT·스포츠 등 | 조선일보, 오마이뉴스, 전자신문, CBS·NBC·ABC·Fox News, The Hill, Politico, LA Times, Axios, Sky News, The Independent, Daily Mail, TechCrunch, The Verge, Wired, Ars Technica, New Scientist 등 |

- **AI 요약 모드**: 위 관심사와 비중이 프롬프트에 들어 있어, 문화예술은 미술계 소식을 최우선으로 국내·해외를 함께 담고 연예 가십은 뺍니다.
- **헤드라인 모드(AI 없음)**: 카테고리별 키워드(전쟁·제재, 증시·환율·금리, 비트코인, 미술·전시·비엔날레 등)로 관련 기사를 우선 고릅니다. 문화예술은 연예 가십을 제외하고 **국내 소식 자리를 최소 3건 확보**합니다. 코인 기사는 어느 피드에 있어도 '코인'으로 모읍니다.
- **중복 제거**: 같은 사건의 `(종합)`·`(종합2보)`·`[속보]` 기사는 하나로 처리합니다. 매일 **자동 실행**에서는 전날 브리핑에 이미 실린 기사를 빼고(수동 실행은 전체 표시), 업데이트가 느린 미술 매체는 48~72시간 이내 기사까지 봅니다.

한계: 국내 미술 전문 매체(월간미술은 2020년 이후 갱신 없음, 아트인컬처·아트뉴스코리아 등은 RSS 불가)는 쓸 수 없어서 **국내 미술 소식은 일반 신문 문화면에 의존**합니다. 그 밖에 중앙일보(RSS 중단), WSJ·CNN(갱신 중단), The Economist(주간), 동아일보(응답 없음), The Art Newspaper·Frieze·ArtReview·Artbasel(접근 불가) 등은 제외했습니다.
RSS 주소는 언제든 바뀔 수 있으니 한동안 안 오는 매체가 있으면 `feeds.json`을 점검하세요.

`samples/2026-11-04.html`은 **이전 카테고리 구성**(AI 요약 모드)으로 만든 샘플이라 현재 구성과 다릅니다.

## 뉴스 소스 바꾸기

`feeds.json`의 `feeds`에 `{ "outlet": "신문사", "region": "국내|미국|영국|기타 해외", "category": "카테고리", "url": "RSS 주소" }`를 추가/삭제하세요. `category`는 `세계 이슈|경제·증시|코인|문화예술|정치·사회|IT·과학|스포츠|종합` 중 하나이며 힌트로 쓰입니다(AI가 최종 분류). 선택 항목: `max_items`(이 피드에서 가져올 최대 기사 수), `max_age_hours`(이 피드만 더 긴 기간 허용). `max_total_articles`(기본 450)는 AI에 보내는 기사 수 상한입니다.

## 로컬 실행

```bash
pip install -r requirements.txt            # (Claude 사용 시 pip install anthropic 추가)
python news_digest.py --no-llm --dry-run   # 키·메일 없이 수집+HTML 생성 (비용 0원)
python news_digest.py --dry-run            # AI 요약까지 (digest.html로 저장)
python news_digest.py                      # 실제 발송 (설정된 채널 전부)
pytest
```
