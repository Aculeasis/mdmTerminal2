
import queue
import threading

from lib.api.api import InternalException
from owner import Owner


class SubscriptionsWorker(threading.Thread):
    def __init__(self, own: Owner):
        super().__init__()
        self.own = own
        self._queue = queue.Queue()
        self.work = True
        self._conn = None
        self._disconnect = False
        self._subscribes = set()
        self.start()

    def run(self) -> None:
        while self.work:
            cmd, item = self._queue.get()
            if not self.work:
                return
            if self._disconnect:
                self._disconnect = False
                self._queue = queue.Queue()
                self._conn = None
            elif cmd is None:
                continue
            elif cmd == 'connect':
                self._queue = queue.Queue()
                self._conn = item
            elif cmd.alive:
                name, args, kwargs = _send_adapter(*item)
                msg = {'method': 'notify.{}'.format(name), 'params': {'args': args, 'kwargs': kwargs}}
                cmd.write(msg)

    def _new_message(self, name, *args, **kwargs):
        self._queue.put_nowait((self._conn, (name, args, kwargs)))

    def connect(self, conn):
        self._queue.put_nowait(('connect', conn))

    def disconnect(self):
        if self._subscribes:
            self.own.unsubscribe(list(self._subscribes), self._new_message)
            self._subscribes.clear()
            self._disconnect = True
            self._queue.put_nowait((None, None))

    def join(self, timeout=5):
        if self.work:
            self.work = False
            self._queue.put_nowait((None, None))
            super().join(timeout)

    def subscribe(self, data: list) -> bool:
        data = _sanitize_subscribe_list(data) - self._subscribes
        self._subscribes.update(data)
        return self.own.subscribe(list(data), self._new_message)

    def unsubscribe(self, data: list) -> bool:
        data = _sanitize_subscribe_list(data) & self._subscribes
        self._subscribes.difference_update(data)
        return self.own.unsubscribe(list(data), self._new_message)


def _sanitize_subscribe_list(data: list) -> set:
    if not data or not isinstance(data, list) or any(True for el in data if not isinstance(el, str) or el == ''):
        raise InternalException(msg='params must be non-empty list<str>')
    return _receive_adapter(set(data))


_ADAPTER_SEND_MAP = {
    'start_talking': ('talking', True),
    'stop_talking': ('talking', False),
    'start_record': ('record', True),
    'stop_record': ('record', False),
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


def _send_adapter(name, args, kwargs) -> tuple:
    if name in _ADAPTER_SEND_MAP:
        args = [_ADAPTER_SEND_MAP[name][1]]
        name = _ADAPTER_SEND_MAP[name][0]
    elif name == 'listener' and args:
        args = [args[0] == 'on']
    return name, args, kwargs
