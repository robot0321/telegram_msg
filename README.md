# Telegram bot

데몬을 켜 두고 `telbot`으로 메시지를 보내거나 Telegram 승인 응답을 기다립니다.

```text
                 credentials.py
                        |
                        v
cli.py (telbot) --> daemon.py --> bot.py <--> Telegram API
```

## 설치

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
# or simply,
pip install -e .
```

## 실행

```bash
# 터미널 1
telegram-msg-daemon --no-initial-unlock

# 터미널 2
telbot unlock
telbot status
```

`unlock`은 `~/.config/telegram/telebot_token.env.age`를 복호화합니다.
데몬을 재시작하면 다시 실행해야 합니다.

## 사용

```bash
telbot send "작업 완료"
telbot request-approval --timeout 60 "진행할까요?"
```

승인 결과는 `approved`(종료 코드 0), `rejected`(1), `timeout`(2)입니다.
Telegram 채팅에서는 `/ping`, `/status`, `/help` 명령을 사용할 수 있습니다.

작업은 DB에 저장하지 않습니다. 데몬이 꺼지거나 통신이 실패하면 호출자가
다시 요청해야 합니다. 재요청 시 Telegram 메시지가 중복될 수 있습니다.
