#!/usr/bin/env bash
set -Eeuo pipefail

USE_VENV=0
case "${1:-}" in
  '') ;;
  --venv) USE_VENV=1; shift ;;
  -h|--help) printf '사용법: %s [--venv]\n기본값: 현재 Python 환경(conda 포함)에 설치합니다.\n' "$0"; exit 0 ;;
  *) printf '알 수 없는 옵션: %s\n' "$1" >&2; exit 1 ;;
esac
(($# == 0)) || { printf '인수가 너무 많습니다.\n' >&2; exit 1; }

printf '%s\n' \
  '1. Python 3, age 및 사용자 systemd 환경을 확인합니다.' \
  '2. 현재 Python 환경에 패키지를 설치합니다(--venv 선택 시 전용 가상환경).' \
  '3. ~/.local/bin 실행 파일과 ~/.config/telegram 디렉터리를 만듭니다.' \
  '4. 사용자 systemd 서비스를 등록하고 잠금 상태로 시작합니다.' \
  '5. 마지막에 암호화 키 파일 위치와 인증 방법을 안내합니다.'

trap 'printf "설치 실패 (줄 %s). 위 오류를 해결한 후 다시 실행하세요.\n" "$LINENO" >&2' ERR
fail() { printf '%s\n' "$*" >&2; exit 1; }

[[ $(id -u) != 0 ]] || fail 'sudo 없이 서비스를 사용할 일반 사용자로 실행하세요.'
[[ $(uname -s) == Linux ]] || fail 'Linux와 사용자 systemd가 필요합니다.'
command -v systemctl >/dev/null || fail 'systemd가 설치된 서버에서 실행하세요.'
systemctl --user show-environment >/dev/null || fail '사용자 systemd에 연결할 수 없습니다. 일반 사용자로 로그인한 세션에서 실행하세요.'

SOURCE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
VENV="$SOURCE_DIR/.venv"
BIN_DIR="$HOME/.local/bin"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/telegram-msg.service"
KEY_DIR="$HOME/.config/telegram"

# 필요한 OS패키지가 없으면 alert후 종료
for cmd in python3 age; do
    command -v "$cmd" >/dev/null ||
        fail "$cmd 가 설치되어 있지 않습니다. 직접 설치해 주세요."
done
python3 -c 'import sys; assert sys.version_info >= (3, 8), "Python 3.8 이상이 필요합니다"'
# 활성화된 conda 환경의 python3를 포함해 PATH에서 선택한 환경을 사용합니다.
PYTHON=$(python3 -c 'import sys; print(sys.executable)')
if ((USE_VENV)); then
  "$PYTHON" -m venv "$VENV"
  PYTHON="$VENV/bin/python"
fi
printf '설치 Python: %s\n' "$PYTHON"
"$PYTHON" -m pip install -e "$SOURCE_DIR"
SCRIPTS_DIR=$("$PYTHON" -c 'import sysconfig; print(sysconfig.get_path("scripts"))')
for name in telbot telegram-msg-daemon; do
  [[ -x "$SCRIPTS_DIR/$name" ]] || fail "설치된 실행 파일을 찾을 수 없습니다: $SCRIPTS_DIR/$name"
done

mkdir -p "$BIN_DIR" "$UNIT_DIR" "$KEY_DIR"
chmod 700 "$KEY_DIR"
for name in telbot telegram-msg-daemon; do
  target="$BIN_DIR/$name"
  [[ "$target" != "$SCRIPTS_DIR/$name" ]] || continue
  if [[ -e "$target" && ! -L "$target" ]]; then
    fail "기존 파일을 덮어쓸 수 없습니다: $target (직접 이동한 후 다시 실행하세요.)"
  fi
  ln -sfn "$SCRIPTS_DIR/$name" "$target"
done

# systemd의 인용 문자열에서 특수문자 및 % specifier를 이스케이프합니다.
exec_path="$SCRIPTS_DIR/telegram-msg-daemon"
[[ "$exec_path" != *$'\n'* && "$exec_path" != *$'\r'* ]] || fail '설치 경로에 줄바꿈을 사용할 수 없습니다.'
exec_path=${exec_path//\\/\\\\}
exec_path=${exec_path//\"/\\\"}
exec_path=${exec_path//%/%%}
exec_path=${exec_path//\$/\$\$}
if [[ -e "$UNIT" ]]; then
  backup=$(mktemp "$UNIT.backup.XXXXXX")
  cp -p -- "$UNIT" "$backup"
  printf '기존 서비스 백업: %s\n' "$backup"
fi
cat > "$UNIT" <<EOF
[Unit]
Description=Telegram message daemon

[Service]
ExecStart="$exec_path" --no-initial-unlock
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
Restart=on-failure

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable telegram-msg.service
systemctl --user restart telegram-msg.service
systemctl --user is-active --quiet telegram-msg.service
"$BIN_DIR/telbot" --help >/dev/null

chmod 600 ~/.config/telegram/telebot_token.env.age
export PATH="$HOME/.local/bin:$PATH"
loginctl enable-linger "$USER"

printf '\n설치 완료!\n'
printf '저장소를 이동하거나 삭제하지 마세요: %s\n' "$SOURCE_DIR"
printf '설치에 사용한 Python 환경도 유지하세요: %s\n' "$PYTHON"
printf '\n마지막 수동 설정:\n'
printf '1. 기존 암호화 키 파일을 다음 위치에 가져다 놓으세요:\n   %s/telebot_token.env.age\n' "$KEY_DIR"
printf '   파일에는 TELBOT_TOKEN과 TELBOT_CHAT_ID가 들어 있어야 합니다.\n'
printf '2. 파일 권한을 제한하고 인증하세요:\n'
printf '   chmod 600 ~/.config/telegram/telebot_token.env.age\n'
printf '   export PATH="$HOME/.local/bin:$PATH"\n'
printf '   telbot unlock\n   telbot status\n'
printf '3. 위 PATH 설정을 ~/.bashrc 또는 ~/.zshrc에도 추가하세요.\n'
printf '\n데몬 재시작 시 telbot unlock을 다시 실행해야 합니다.\n'
printf '로그아웃 후에도 서비스를 유지하려면: loginctl enable-linger "%s"\n' "$(id -un)"
