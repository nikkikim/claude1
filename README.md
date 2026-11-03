# 📰 Daily News Digest

주요 뉴스를 RSS로 모아 Claude가 한국어로 요약하고, 매일 아침 **이메일 및/또는 텔레그램**으로 보내줍니다.
GitHub Actions로 돌아가므로 서버가 필요 없습니다.

## 설정 (한 번만)

1. **Claude API 키** 발급 → https://console.anthropic.com
2. (이메일을 쓸 때) **Gmail 앱 비밀번호** 발급 (2단계 인증 필요) → https://myaccount.google.com/apppasswords
   (다른 SMTP를 쓰려면 Repository variables에 `SMTP_HOST`, `SMTP_PORT` 설정)
3. GitHub 저장소 → Settings → Secrets and variables → Actions → **Secrets** 추가:

| Secret | 값 |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API 키 |
| `SMTP_USER` | 발신 Gmail 주소 |
| `SMTP_PASSWORD` | 앱 비밀번호 |
| `MAIL_TO` | 수신 주소 (쉼표로 여러 명) |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 텔레그램 채팅 ID (쉼표로 여러 개) |

값이 설정된 채널로만 발송됩니다. 이메일만, 텔레그램만, 또는 둘 다 가능합니다.

## 텔레그램 설정

1. 텔레그램에서 **@BotFather** → `/newbot` → 이름 지정 → **토큰** 받기
2. 만든 봇과의 대화창에서 아무 메시지(`/start`)나 보내기
3. 브라우저에서 `https://api.telegram.org/bot<토큰>/getUpdates` 를 열어 `"chat":{"id":123456789,...}` 의 숫자가 **채팅 ID**
   (그룹/채널로 받으려면 봇을 초대·관리자 추가 후 그 ID 사용. 그룹·채널 ID는 음수)
4. 토큰과 채팅 ID를 위 표의 Secrets에 등록

4. (텔레그램을 쓸 때) 아래 "텔레그램 설정" 참고
5. Actions 탭 → **Daily News Digest** → *Run workflow* 로 수동 테스트.

기본 발송 시각은 매일 07:30 KST (`.github/workflows/daily-news.yml`의 cron 수정).
참고: GitHub 스케줄은 수 분~수십 분 늦을 수 있고, 기본 브랜치에 있어야 동작합니다.

## 참고하는 신문사 / 카테고리

**국내 (8)**: 연합뉴스, 조선일보, 한겨레, 경향신문, 한국경제, 매일경제, 오마이뉴스, 전자신문
**해외 (12)**: BBC, NYT, The Guardian, Al Jazeera, DW, Financial Times, Japan Times, SCMP, Nikkei Asia, TechCrunch, The Verge, Ars Technica

**카테고리 (고정 순서)**: 정치 · 경제 · 사회 · 국제 · IT·과학 · 문화·스포츠
같은 사건을 여러 신문사가 다루면 하나로 묶고 보도한 신문사를 함께 표시하며, 메일 하단에 그날 실제로 수집된 신문사 목록이 붙습니다.

`samples/2026-11-04.html` 은 이 구성으로 만든 샘플 메일입니다
(API 키 없이 수집한 기사를 직접 요약해 만든 예시이며, 실제 발송분은 Claude API가 같은 프롬프트로 생성합니다).

일부 피드는 제외했습니다: 중앙일보(RSS 중단), WSJ·CNN(갱신 중단), The Economist(주간), 동아일보(응답 없음), 한국일보·서울신문·NPR·Washington Post(접근 불가).
조선일보 RSS는 연예·스포츠·일본어판 기사가 많이 섞여 있어 요약 품질에 한계가 있습니다.

## 뉴스 소스 바꾸기

`feeds.json`의 `feeds`에 `{ "outlet": "신문사", "region": "국내|해외", "category": "정치|경제|사회|국제|IT·과학|문화·스포츠|종합", "url": "RSS 주소" }`를 추가/삭제하세요. `category`는 힌트이며 Claude가 내용에 맞게 최종 분류합니다.
(일부 사이트는 http RSS를 막으므로 https 주소를 쓰세요.)

## 로컬 실행

```bash
pip install -r requirements.txt
python news_digest.py --no-llm --dry-run   # API 키/메일 없이 수집+HTML 생성 확인
python news_digest.py --dry-run            # Claude 요약까지 (digest.html로 저장)
python news_digest.py                      # 실제 발송 (설정된 채널 전부)
pytest
```

비용: 하루 1회, 기사 ~100건 입력 → 요약 호출 1회라 월 수백 원 수준입니다.
