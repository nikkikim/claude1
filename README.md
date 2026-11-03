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

## 뉴스 소스 바꾸기

`feeds.json`의 `feeds`에 `{ "name": "...", "url": "RSS 주소" }`를 추가/삭제하세요.
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
