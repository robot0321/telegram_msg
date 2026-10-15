"""다른 Python 코드에서도 사용할 수 있는 데몬 통신 함수."""

from __future__ import annotations

import json
import socket
from typing import Optional

from telegram_bot.config import default_socket_path


def call_daemon(request: dict, socket_path: Optional[str] = None, timeout: int = 10) -> dict:
    """Unix socket으로 JSON 한 줄을 보내고 JSON 한 줄을 받는다."""
    if socket_path is None:
        socket_path = str(default_socket_path())
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
