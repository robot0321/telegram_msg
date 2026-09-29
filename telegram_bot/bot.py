import logging
import threading

log = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, token='', chat_id='', session=None):
        self.token = str(token)
        self.chat_id = str(chat_id)
        self.enabled = bool(token and chat_id)
        self.url = f'https://api.telegram.org/bot{token}/'
        self.session = session
        self._thread_sessions = threading.local()

    def _session(self):
        if self.session is not None:
            return self.session
        if not hasattr(self._thread_sessions, 'session'):
            import requests
            self._thread_sessions.session = requests.Session()
        return self._thread_sessions.session

    def call(self, method, payload):
        # Do not log request exceptions: their URLs can contain the bot token.
        try:
            response = self._session().post(self.url + method, json=payload, timeout=(5, 35))
            response.raise_for_status()
            data = response.json()
            if not data.get('ok'):
                raise RuntimeError('Telegram API rejected request')
            return data['result']
        except Exception:
            raise RuntimeError(f'Telegram {method} failed') from None

    def send_message(self, text):
        if not self.enabled:
            log.info('Telegram disabled: %s', text)
            return
        for start in range(0, len(text), 2000):
            self.call('sendMessage', {'chat_id': self.chat_id, 'text': text[start:start + 2000]})

    def ask_approval(self, text, approval_id):
        if not approval_id or len(('approve:' + approval_id).encode()) > 64:
            raise ValueError('approval_id must fit Telegram callback_data (64 bytes)')
        if not self.enabled:
            log.info('Telegram disabled; approval pending: %s', approval_id)
            return
        self.call('sendMessage', {'chat_id': self.chat_id, 'text': text[:2000], 'reply_markup': {
            'inline_keyboard': [[{'text': 'Approve', 'callback_data': 'approve:' + approval_id},
                                 {'text': 'Reject', 'callback_data': 'reject:' + approval_id}]]}})

    def answer_callback_query(self, callback_query_id, text):
        """버튼을 누른 Telegram 사용자에게 처리 결과를 보여준다."""
        self.call('answerCallbackQuery', {
            'callback_query_id': callback_query_id,
            'text': text,
        })

    def event_from_update(self, update):
        query = update.get('callback_query')
        message = query.get('message', {}) if query else update.get('message', {})
        # Private chat: the configured recipient is also the authorized approver.
        if str(message.get('chat', {}).get('id')) != self.chat_id:
            return None
        sender = query.get('from', {}) if query else message.get('from', {})
        if str(sender.get('id')) != self.chat_id:
            return None
        if query:
            action, separator, approval_id = query.get('data', '').partition(':')
            if separator and approval_id and action in ('approve', 'reject'):
                return {'type': 'approval', 'approval_id': approval_id,
                        'approved': action == 'approve', 'callback_query_id': query['id']}
        elif 'text' in message:
            return {'type': 'telegram_message', 'text': message['text']}
        return None

    def listen(self, on_event, stop):
        """각 update를 처리한 다음에만 다음 offset으로 넘어간다."""
        offset = None
        while not stop.is_set():
            try:
                updates = self.call('getUpdates', {'offset': offset, 'timeout': 25,
                                                  'allowed_updates': ['message', 'callback_query']})
                for update in updates:
                    event = self.event_from_update(update)
                    if event:
                        on_event(event)
                    offset = update['update_id'] + 1
            except Exception:
                log.warning('Telegram polling failed; retrying in 5 seconds')
                stop.wait(5)
