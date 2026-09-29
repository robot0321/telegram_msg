"""Decrypt selected startup credentials in memory; age owns the terminal prompt."""
from dataclasses import dataclass, field
from pathlib import Path
import shlex
import subprocess

KEY_FILE = Path('~/.config/telegram/telebot_token.env.age').expanduser()
KNOWN_KEYS = ('TELBOT_TOKEN', 'TELBOT_CHAT_ID')
REQUIRED_KEYS = KNOWN_KEYS  # Backward-compatible default for legacy callers.


@dataclass(frozen=True)
class Credentials:
    telegram_token: str = field(default='', repr=False)
    telegram_chat_id: str = field(default='', repr=False)


class CredentialError(RuntimeError):
    pass


def load_credentials(path=KEY_FILE, required_keys=REQUIRED_KEYS, timeout=None):
    # 호출자가 요구한 키만 필수로 검사하므로 Phase별 최소 권한 구성이 가능하다.
    required_keys = tuple(required_keys)
    unknown = set(required_keys) - set(KNOWN_KEYS)
    if unknown:
        raise ValueError('Unknown credential key requested')
    
    # 암호화 파일이 없으면 평문 환경변수로 우회하지 않고 즉시 실패한다.
    if not Path(path).is_file():
        raise CredentialError(f'Credential file not found: {path}')
    try:
        # Inherit stdin/stderr so age can request a passphrase through the terminal.
        # age가 현재 터미널에서 비밀번호를 받고, 평문은 stdout 메모리로만 전달한다.
        print("Authorizing access to Telegram credentials...")
        result = subprocess.run(['age', '--decrypt', str(path)], stdout=subprocess.PIPE,
                                check=True, timeout=timeout)
    except FileNotFoundError:
        raise CredentialError('age is required to decrypt credentials; install age first') from None
    except subprocess.CalledProcessError:
        raise CredentialError('age decryption failed; credentials were not loaded') from None
    except subprocess.TimeoutExpired:
        raise CredentialError('credential unlock timed out') from None
    except OSError:
        raise CredentialError('Unable to run age to decrypt credentials') from None
    
    # 복호화된 각 줄을 shell 실행 없이 NAME=value 형식으로만 파싱한다.
    values = {}
    try:
        for line in result.stdout.decode('utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:].lstrip()
            name, separator, raw = line.partition('=')
            if not separator:
                raise ValueError
            name = name.strip()
            if name not in KNOWN_KEYS:
                continue
            parts = shlex.split(raw, comments=True, posix=True)
            if len(parts) != 1 or name in values or '\0' in parts[0]:
                raise ValueError
            values[name] = parts[0]
    except (UnicodeError, ValueError):
        raise CredentialError('Invalid credential file; use unique NAME=value entries (quote spaces)') from None
    
    # 요청한 profile에 필요한 값이 하나라도 없으면 부분 자격증명을 반환하지 않는다.
    missing = [name for name in required_keys if not values.get(name)]
    if missing:
        raise CredentialError('Missing credentials: ' + ', '.join(missing))
    return Credentials(
        telegram_token=values.get('TELBOT_TOKEN', ''),
        telegram_chat_id=values.get('TELBOT_CHAT_ID', ''),
    )


if __name__ == '__main__':
    # Standalone test: decrypt and print all known keys.
    try:
        creds = load_credentials()
    except CredentialError as exc:
        raise SystemExit(str(exc)) from None
    # 실제 값 대신 존재 여부만 출력해 terminal history 노출을 막는다.
    print(f'TELBOT_TOKEN loaded={bool(creds.telegram_token)}')
    print(f'TELBOT_CHAT_ID loaded={bool(creds.telegram_chat_id)}')
