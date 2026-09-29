"""Telegram 메시지와 승인 요청을 처리하는 로컬 데몬."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import signal
import socket
import socketserver
import threading
import uuid

from telegram_bot import TelegramBot
from telegram_bot.config import default_socket_path
from telegram_bot.credentials import CredentialError, KEY_FILE, load_credentials


log = logging.getLogger(__name__)


@dataclass
class PendingApproval:
    """현재 연결에서 답변을 기다리는 승인 요청."""

    done: threading.Event
    result: str | None = None


class TelegramService:
    """메시지를 바로 보내고 진행 중인 승인만 메모리에 보관한다."""

    def __init__(self, stop: threading.Event):
        self.stop = stop
        self.bot: TelegramBot | None = None
        self.lock = threading.Lock()
        self.pending: dict[str, PendingApproval] = {}

    def unlock(self, token: str, chat_id: str) -> bool:
        """credential을 메모리에 올리고 Telegram polling을 시작한다."""
        if not token or not chat_id:
            raise ValueError("token and chat_id are required")
        with self.lock:
            if self.bot is not None:
                return False
            self.bot = TelegramBot(token, chat_id)

        threading.Thread(
            target=self.bot.listen,
            args=(self._process_event, self.stop),
            name="telegram-listener",
            daemon=True,
        ).start()
        log.info("Telegram credential unlocked")
        return True

    def status(self) -> dict:
        with self.lock:
            return {
                "ok": True,
                "telegram": "ready" if self.bot is not None else "locked",
                "pending_approvals": len(self.pending),
            }

    def send(self, text: str) -> dict:
        self._ready_bot().send_message(text)
        return {"ok": True, "status": "sent"}

    def request_approval(self, text: str, timeout: int) -> dict:
        bot = self._ready_bot()
        approval_id = uuid.uuid4().hex
        approval = PendingApproval(done=threading.Event())
        with self.lock:
            self.pending[approval_id] = approval

        try:
            bot.ask_approval(text, approval_id)
        except Exception:
            with self.lock:
                self.pending.pop(approval_id, None)
            raise

        approval.done.wait(timeout)
        with self.lock:
            self.pending.pop(approval_id, None)
            result = approval.result or "timeout"
        return {"ok": True, "approval_id": approval_id, "result": result}

    def _ready_bot(self) -> TelegramBot:
        with self.lock:
            if self.bot is None:
                raise RuntimeError("Telegram credential is locked; run telbot unlock")
            return self.bot

    def _process_event(self, event: dict) -> None:
        """Telegram polling thread가 메시지와 승인 버튼을 전달한다."""
        if event["type"] == "telegram_message":
            self._handle_telegram_message(event["text"])
            return
        if event["type"] != "approval":
            return

        with self.lock:
            approval = self.pending.get(event["approval_id"])
            if approval is not None and approval.result is None:
                approval.result = "approved" if event["approved"] else "rejected"
                approval.done.set()
                result = approval.result
            else:
                result = None
        message = {
            "approved": "승인되었습니다.",
            "rejected": "거절되었습니다.",
        }.get(result, "이미 처리되거나 만료된 요청입니다.")
        try:
            self._ready_bot().answer_callback_query(event["callback_query_id"], message)
        except RuntimeError:
            log.warning("Failed to acknowledge Telegram callback")

    def _handle_telegram_message(self, text: str) -> None:
        """허용한 명령에만 답한다. 일반 메시지는 사용법을 안내한다."""
        command = text.strip()
        if command == "/ping":
            reply = "pong"
        elif command == "/status":
            status = self.status()
            reply = (
                f"Telegram: {status['telegram']}\n"
                f"Pending approvals: {status['pending_approvals']}"
            )
        elif command in ("/start", "/help"):
            reply = "사용 가능한 명령: /ping, /status, /help"
        else:
            reply = "알 수 없는 명령입니다. /help를 입력하세요."

        try:
            self._ready_bot().send_message(reply)
        except RuntimeError:
            log.warning("Failed to reply to Telegram message")


class RequestHandler(socketserver.StreamRequestHandler):
    """한 줄짜리 JSON 요청 하나를 처리한다."""

    def handle(self) -> None:
        try:
            line = self.rfile.readline(1_000_001)
            if not line or len(line) > 1_000_000:
                raise ValueError("request is empty or too large")
            request = json.loads(line)
            response = self.dispatch(request)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            response = {"ok": False, "error": f"invalid request: {exc}"}
        except RuntimeError as exc:
            response = {"ok": False, "error": str(exc)}
        except Exception:
            log.exception("Request failed")
            response = {"ok": False, "error": "internal error"}

        self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")

    def dispatch(self, request: dict) -> dict:
        service: TelegramService = self.server.service
        operation = request["op"]

        if operation == "status":
            return service.status()
        if operation == "unlock":
            changed = service.unlock(str(request["token"]), str(request["chat_id"]))
            return {"ok": True, "status": "unlocked" if changed else "already_unlocked"}
        if operation == "message.send":
            return service.send(_text(request))
        if operation == "approval.request":
            timeout = int(request.get("timeout_seconds", 300))
            if not 1 <= timeout <= 3600:
                raise ValueError("timeout_seconds must be between 1 and 3600")
            return service.request_approval(_text(request), timeout)
        raise ValueError(f"unknown operation: {operation}")


def _text(request: dict) -> str:
    text = str(request["text"]).strip()
    if not text:
        raise ValueError("text must not be empty")
    return text


class ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str, service: TelegramService):
        self.service = service
        super().__init__(path, RequestHandler)


def try_initial_unlock(service: TelegramService, credential_file: str, timeout: int) -> None:
    """시작 터미널에서만 입력을 기다리고, 실패해도 데몬은 유지한다."""
    try:
        credentials = load_credentials(credential_file, timeout=timeout)
        service.unlock(credentials.telegram_token, credentials.telegram_chat_id)
    except CredentialError as exc:
        log.warning("Initial unlock skipped: %s", exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default=str(default_socket_path()))
    parser.add_argument("--credential-file", default=str(KEY_FILE))
    parser.add_argument("--initial-unlock-timeout", type=int, default=60)
    parser.add_argument("--no-initial-unlock", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    socket_path = Path(args.socket)
    socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if socket_path.exists():
        if not socket_path.is_socket():
            raise SystemExit(f"Refusing to replace non-socket path: {socket_path}")
        # 실행 중인 데몬의 socket은 건드리지 않고, 죽은 데몬의 잔여 socket만 지운다.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            try:
                probe.connect(str(socket_path))
            except ConnectionRefusedError:
                socket_path.unlink()
            except OSError as exc:
                raise SystemExit(f"Unable to check existing socket: {exc}") from None
            else:
                raise SystemExit(f"Daemon is already running at {socket_path}")

    stop = threading.Event()
    service = TelegramService(stop)
    server = ThreadingUnixServer(str(socket_path), service)
    os.chmod(socket_path, 0o600)

    def shutdown(signum, frame):
        stop.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    server_thread = threading.Thread(target=server.serve_forever, name="local-api", daemon=True)
    server_thread.start()
    log.info("Telegram daemon listening on %s", socket_path)

    if not args.no_initial_unlock:
        threading.Thread(
            target=try_initial_unlock,
            args=(service, args.credential_file, args.initial_unlock_timeout),
            name="initial-unlock",
            daemon=True,
        ).start()

    try:
        stop.wait()
        return 0
    finally:
        server.shutdown()
        server.server_close()
        socket_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
