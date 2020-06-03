
import queue
import threading

from lib.api.api import InternalException
from lib.socket_wrapper import Connect
from owner import Owner


class SubscriptionsWorker(threading.Thread):
    def __init__(self, own: Owner, conn: Connect):
        super().__init__()
        self.own = own
        self._conn = conn
        self._queue = queue.Queue()
        self._subscribes = set()
        self.work = True
        self.start()

    def run(self) -> None:
        while self.work:
            notify = self._queue.get()
            if notify is None:
                break
            elif self._conn.alive:
                name, args, kwargs = _send_adapter(*notify)
                msg = {'method': 'notify.{}'.format(name), 'params': {'args': args, 'kwargs': kwargs}}
                self._conn.write(msg)
            else:
                break
        self._unsubscribe_all()

    def _new_message(self, name, *args, **kwargs):
        if self.work:
            self._queue.put_nowait((name, args, kwargs))

    def _unsubscribe_all(self):
        self.work = False
        if self._subscribes:
            self.own.unsubscribe(list(self._subscribes), self._new_message)
            self._subscribes.clear()

    def close_signal(self):
        self._queue.put_nowait(None)
        self.work = False

    def join(self, timeout=5):
        self.close_signal()
        super().join(timeout)

    def subscribe(self, data: list) -> bool:
        if not self.work:
            return False
        data = _sanitize_subscribe_list(data) - self._subscribes
        self._subscribes.update(data)
        return self.own.subscribe(list(data), self._new_message)

    def unsubscribe(self, data: list) -> bool:
        if not self.work:
            return False
        data = _sanitize_subscribe_list(data) & self._subscribes
        self._subscribes.difference_update(data)
        return self.own.unsubscribe(list(data), self._new_message)

    def events_list(self) -> list:
        return _send_list_adapter(self.own.events_list()) if self.work else []


def _sanitize_subscribe_list(data: list) -> set:
    if not data or not isinstance(data, list) or any(True for el in data if not isinstance(el, str) or el == ''):
        raise InternalException(msg='params must be non-empty list<str>')
    return _receive_adapter(set(data))


_ADAPTER_SEND_MAP = {
    'start_talking': ('talking', True),
    'stop_talking': ('talking', False),
    'start_record': ('record', True),
    'stop_record': ('record', False),
    'start_stt_event': ('stt_event', True),
    'stop_stt_event': ('stt_event', False),
}

_ADAPTER_RECEIVE_MAP = {}


def __make():
    for key, (val, _) in _ADAPTER_SEND_MAP.items():
        if val not in _ADAPTER_RECEIVE_MAP:
            _ADAPTER_RECEIVE_MAP[val] = set()
        _ADAPTER_RECEIVE_MAP[val].add(key)


__make()


def _receive_adapter(subscriptions: set) -> set:
    for key in list(subscriptions):
        if key in _ADAPTER_RECEIVE_MAP:
            subscriptions.discard(key)
            subscriptions.update(_ADAPTER_RECEIVE_MAP[key])
    return subscriptions


def _send_list_adapter(events: list) -> list:
    return list({_ADAPTER_SEND_MAP.get(key, (key,))[0] for key in events})


def _send_adapter(name, args, kwargs) -> tuple:
    if name in _ADAPTER_SEND_MAP:
        args = [_ADAPTER_SEND_MAP[name][1]]
        name = _ADAPTER_SEND_MAP[name][0]
    elif name == 'listener' and args:
        args = [args[0] == 'on']
    return name, args, kwargs
