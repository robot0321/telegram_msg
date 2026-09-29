"""CLI와 데몬이 함께 쓰는 로컬 설정."""

import os
from pathlib import Path


def default_socket_path() -> Path:
    """같은 사용자의 CLI와 데몬이 접속할 Unix socket 경로."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "telegram-msg.sock"
    return Path("/tmp") / f"telegram-msg-{os.getuid()}" / "telegram-msg.sock"
