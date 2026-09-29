"""telbot 명령줄 클라이언트."""

from __future__ import annotations

import argparse
import json
import socket
import sys

from telegram_bot.config import default_socket_path
from telegram_bot.credentials import CredentialError, KEY_FILE, load_credentials


def call_daemon(socket_path: str, request: dict, timeout: int = 10) -> dict:
    """Unix socket으로 JSON 한 줄을 보내고 JSON 한 줄을 받는다."""
    payload = json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        try:
            client.connect(socket_path)
        except FileNotFoundError:
            raise RuntimeError(
                f"daemon socket not found: {socket_path}. "
                "Start telegram-msg-daemon first."
            ) from None
        except ConnectionRefusedError:
            raise RuntimeError(
                f"daemon is not listening on {socket_path}. "
                "Check telegram-msg-daemon."
            ) from None
        client.sendall(payload)

        response = bytearray()
        while b"\n" not in response:
            chunk = client.recv(4096)
            if not chunk:
                raise RuntimeError("daemon closed the connection")
            response.extend(chunk)

    line, _, _ = response.partition(b"\n")
    return json.loads(line)


def show_result(response: dict) -> int:
    if not response.get("ok"):
        print(f"telbot: {response.get('error', 'request failed')}", file=sys.stderr)
        return 1
    print(json.dumps(response, ensure_ascii=False, indent=2), flush=True)
    return 0


def command_status(args) -> int:
    return show_result(call_daemon(args.socket, {"op": "status"}))


def command_unlock(args) -> int:
    # age가 이 CLI의 터미널에서 암호를 묻는다. 평문 credential은 저장하지 않는다.
    call_daemon(args.socket, {"op": "status"})
    credentials = load_credentials(args.credential_file)
    return show_result(call_daemon(args.socket, {
        "op": "unlock",
        "token": credentials.telegram_token,
        "chat_id": credentials.telegram_chat_id,
    }))


def command_send(args) -> int:
    return show_result(call_daemon(args.socket, {
        "op": "message.send",
        "text": args.text,
    }, timeout=45 * max(1, (len(args.text) + 1999) // 2000)))


def command_approval(args) -> int:
    response = call_daemon(args.socket, {
        "op": "approval.request",
        "text": args.text,
        "timeout_seconds": args.timeout,
    }, timeout=args.timeout + 45)

    if not response.get("ok"):
        return show_result(response)

    result = response["result"]
    print(result, flush=True)
    return {"approved": 0, "rejected": 1, "timeout": 2}[result]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telbot")
    parser.add_argument("--socket", default=str(default_socket_path()))
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="show daemon status")
    status.set_defaults(handler=command_status)

    unlock = subparsers.add_parser("unlock", help="load Telegram credential")
    unlock.add_argument("--credential-file", default=str(KEY_FILE))
    unlock.set_defaults(handler=command_unlock)

    send = subparsers.add_parser("send", help="send a Telegram message")
    send.add_argument("text")
    send.set_defaults(handler=command_send)

    approval = subparsers.add_parser("request-approval", help="wait for approve/reject button")
    approval.add_argument("text")
    approval.add_argument("--timeout", type=int, default=300)
    approval.set_defaults(handler=command_approval)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except CredentialError as exc:
        print(f"telbot: {exc}", file=sys.stderr)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"telbot: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
