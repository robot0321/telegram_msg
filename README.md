# Telegram bot

데몬을 켜 두고 `telbot`으로 메시지를 보내거나 Telegram 승인 응답을 기다립니다.

```text
                           credentials.py
                                  |
                                  v
cli.py (telbot) --> client.py --> daemon.py --> bot.py <--> Telegram API
```

## 설치

현재 활성화된 Python 환경에 설치하는 것이 기본값입니다. conda를 사용한다면
원하는 환경을 활성화한 뒤 실행하세요. 설치 스크립트는 서비스를 등록하고 재시작합니다.

```bash
conda activate <환경명>  # conda 사용 시
./install.sh

# 별도 .venv를 만들고 싶을 때만
./install.sh --venv

# 서비스 등록 없이 패키지만 설치
python3 -m pip install -e .
```

서비스는 설치한 환경의 실행 파일 절대 경로를 사용하므로, 이후 터미널에서
conda 환경을 활성화하지 않아도 실행됩니다. 해당 환경과 저장소는 유지해야 합니다.

`telegram_bot`을 import하려면 **그 코드를 실행하는 Python 환경**에 패키지가 설치되어 있어야 합니다.
가상환경을 쓰지 않는 동일한 사용자 Python에서 공통으로 쓰고 싶다면
`python3 -m pip install --user -e .`로 설치할 수 있습니다(배포판에서 사용자 설치를
막는 경우는 제외). 별도의 가상환경에서는 각각 설치해야 하며, `PATH` 설정은 import와 무관합니다.

## systemd 등록 (선택)

* `~/.config/systemd/user/telegram-msg.service`를 만들고 아래 내용을 넣습니다. (디렉터리 생성 포함)
* `ExecStart`의 경로는 위에서 설치한 경로로 바꿔야 합니다. 
(예시: `~/bin/telegram-msg-daemon` or `~/venv/bin/telegram-msg-daemon` or `~/anaconda3/bin/telegram-msg-daemon` 등)

```ini
[Unit]
Description=Telegram message daemon

[Service]
ExecStart=/absolute/path/to/telegram-msg-daemon --no-initial-unlock
Restart=on-failure

[Install]
WantedBy=default.target
```

* `.service` 파일을 만든 다음에 다음을 실행하세요
```bash
systemctl --user daemon-reload
systemctl --user enable --now telegram-msg.service
systemctl --user status telegram-msg.service
```

* 데몬 시작 후에는 `telbot unlock`을 실행해서 인증을 완료해야 사용 가능합니다.

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

`telbot send`는 메시지 맨 앞에 `@<서버이름>/<현재실행폴더>\n`을 자동으로 붙입니다.
서버 이름은 호스트명이며, 현재 실행 폴더는 명령을 실행한 디렉터리의 마지막 이름입니다.
예를 들어 `my-server`의 `/home/user/project`에서 실행하면 다음처럼 전송됩니다.

```text
@my-server/project
작업 완료
```

승인 결과는 `approved`(종료 코드 0), `rejected`(1), `timeout`(2)입니다.
Telegram 채팅에서는 `/ping`, `/status`, `/help` 명령을 사용할 수 있습니다.

작업은 DB에 저장하지 않습니다. 데몬이 꺼지거나 통신이 실패하면 호출자가
다시 요청해야 합니다. 재요청 시 Telegram 메시지가 중복될 수 있습니다.

## 다른 Python 코드에서 사용

```python
from telegram_bot.client import call_daemon

response = call_daemon(
    {"op": "approval.request", "text": "진행할까요?", "timeout_seconds": 60},
    timeout=105,  # 승인 대기 시간 + 통신 여유
)
if not response["ok"]:
    raise RuntimeError(response["error"])

if response["result"] == "approved":
    print("진행")
```

`response["result"]`는 `approved`, `rejected`, `timeout` 중 하나입니다.
메시지 전송은 `{"op": "message.send", "text": "작업 완료"}` 요청을 사용합니다.

## 에러 리포트

`importlib.metadata.PackageNotFoundError: telegram-msg` 에러
- conda나 pip 이슈나 기타 패키지 수정으로 패키지가 없어진거니, 소스 코드 폴더 가서 `pip install -e .` 하면 해결
