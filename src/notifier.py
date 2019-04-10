#!/usr/bin/env python3

import queue
import threading
import time
import urllib.parse
from functools import lru_cache

import requests

import logger
from lib.outgoing_socket import OutgoingSocket
from owner import Owner
from utils import REQUEST_ERRORS


class MajordomoNotifier(threading.Thread):
    FILE = 'notifications'
    EVENTS = ('speech_recognized_unsuccess', 'speech_recognized_success', 'voice_activated', 'ask_again',
              'music_status', 'start_record', 'stop_record', 'start_talking', 'stop_talking',)

    def __init__(self, cfg, log, owner: Owner):
        super().__init__(name='Notifier')
        self.cfg = cfg
        self._cfg = cfg['smarthome']
        self.log = log
        self.own = owner
        self._work = False
        self._queue = MyQueue(maxsize=50)
        self._lock = threading.Lock()
        self._boot_time = None
        self._skip = SkipNotifications()
        self._self_events = ('volume', 'music_volume', 'updater', 'listener', 'version')
        self._events = ()
        self.outgoing = OutgoingSocket(self._cfg, log.add('O'), self.own)

    def list_notifications(self) -> list:
        with self._lock:
            return list(self._events)

    def add_notifications(self, events: list) -> list:
        added = []
        events = set(events)
        with self._lock:
            for event in events:
                if not isinstance(event, str):
                    continue
                event = event.lower()
                if event not in self._events and event != '*':
                    added.append(event)
            if added:
                self._unsubscribe()
                self._events += tuple(added)
                self._subscribe()
        return added

    def remove_notifications(self, events: list) -> list:
        removed = []
        events = set(events)
        with self._lock:
            new = set(self._events)
            for event in events:
                if not isinstance(event, str):
                    continue
                event = event.lower()
                if event == '*':
                    removed.extend(new)
                    new.clear()
                    break
                if event in new:
                    removed.append(event)
                    new.discard(event)
            if removed:
                self._unsubscribe()
                self._events = tuple(new)
                self._subscribe()
        return removed

    def _load(self):
        data = self.cfg.load_dict(self.FILE)
        if isinstance(data, dict) and isinstance(data.get('events'), list):
            self._events = tuple(data['events'])
        else:
            self._events = self.EVENTS + self._self_events

    def _save(self):
        self.cfg.save_dict(self.FILE, {'events': self._events})

    def _subscribe(self):
        # Подписываемся на нужные события, если нужно
        if self._allow_notify:
            self.own.subscribe(self._events, self._callback)

    def _unsubscribe(self):
        self.own.unsubscribe(self._events, self._callback)

    def reload(self, diff: dict):
        with self._lock:
            self._make_url.cache_clear()
            self._skip.clear()
            self._unsubscribe()
            self._subscribe()
            self._queue.put_nowait(None)
            if 'outgoing_socket' in diff.get('smarthome', {}):
                self.outgoing.reload()

    def start(self):
        self._work = True
        self._load()
        self.log('start', logger.INFO)
        self._subscribe()
        super().start()
        self.outgoing.start()

    def join(self, timeout=None):
        if self._work:
            self._work = False
            self._save()
            self._queue.put_nowait(None)
            self.log('stopping...', logger.DEBUG)
            super().join()
            self.outgoing.join(20)
            self.log('stop.', logger.INFO)

    def run(self):
        def ignore():
            return not self._allow_notify or self._skip.is_skip
        while self._work:
            to_sleep = self._cfg['heartbeat_timeout']
            if to_sleep <= 0:
                to_sleep = None
            try:
                data = self._queue.get(timeout=to_sleep)
            except queue.Empty:
                if ignore():
                    continue
                # Отправляем пинг на сервер
                data = self.own.get_volume_status
                data['uptime'] = self._uptime
            else:
                if not isinstance(data, dict) or ignore():
                    continue
            self._send_notify(data)

    def send(self, qry: str, user=None) -> str:
        return self._send('cmd', {'qry': qry}, user)

    @property
    def _uptime(self) -> int:
        if self._boot_time is None:
            self._boot_time = _get_boot_time()
        # Считаем uptime от времени загрузки, так быстрее чем каждый раз дергать его из фс.
        return int(time.time() - self._boot_time)

    @property
    def _allow_notify(self) -> bool:
        return self._cfg['object_name'] and self._cfg['object_method'] and self.own.outgoing_available

    def _callback(self, name, data=None, *_, **__):
        if not self._allow_notify:
            return
        kwargs = {'uptime': self._uptime}
        if name in self._self_events:
            kwargs[name] = data
        elif name == 'music_status':
            kwargs['status'] = 'music_{}'.format(data)
        else:
            kwargs['status'] = name
        self._queue.put_nowait(kwargs)

    def _send_notify(self, params: dict):
        try:
            self._send('api', params)
        except RuntimeError as e:
            self._skip.got_error()
            self.log(e, logger.ERROR)
        else:
            self._skip.clear()

    def _send(self, target: str, params: dict, user=None) -> str:
        # https://github.com/sergejey/majordomo-chromegate/blob/master/js/main.js#L196
        terminal = self._cfg['terminal']
        username = self._cfg['username']
        password = self._cfg['password']
        calling_user = user or username

        auth = (username, password) if username and password else None
        if terminal:
            params['terminal'] = terminal
        if calling_user:
            params['username'] = calling_user
        if self.own.duplex_mode_on:
            return self._send_over_socket(target, params)
        else:
            return self._send_over_http(target, params, auth)

    @lru_cache(maxsize=2)
    def _make_url(self, target: str) -> str:
        ip = self._cfg['ip']
        if not ip or self._cfg['disable_http']:
            return ''
        elif target == 'api':
            target_path = 'api/method/{}.{}'.format(self._cfg['object_name'], self._cfg['object_method'])
        elif target == 'cmd':
            target_path = 'command.php'
        else:
            return ''
        url = urllib.parse.urlparse(ip)
        scheme = url.scheme or 'http'
        hostname = url.hostname or ip
        path = url.path.rstrip('/') if url.hostname and url.path and url.path != '/' else ''
        port = ':{}'.format(url.port) if url.port else ''
        return '{}://{}{}{}/{}'.format(scheme, hostname, port, path, target_path)

    def _send_over_http(self, target: str, params: dict, auth: tuple or None) -> str:
        url = self._make_url(target)
        if not url:
            return 'http disabled'
        try:
            reply = requests.get(url, params=params, auth=auth, timeout=30)
        except REQUEST_ERRORS as e:
            raise RuntimeError(e)
        if not reply.ok:
            raise RuntimeError('Server reply error from \'{}\'. {}: {}'.format(url, reply.status_code, reply.reason))
        return reply.request.url

    def _send_over_socket(self, target: str, params: dict) -> str:
        self.own.send_on_duplex_mode({'method': target, 'params': params})
        return 'in socket {}: {}'.format(target, repr(params)[:300])


class MyQueue(queue.Queue):
    def put_nowait(self, item):
        try:
            super().put_nowait(item)
        except queue.Full:
            pass


class SkipNotifications:
    MAX_ERROR_COUNT = 10
    WAIT_ON_ERROR = 5 * 60  # max 10 * 5 minutes

    def __init__(self):
        self._errors = 0
        self._skip_to = 0.0

    def clear(self):
        self._errors = 0

    def got_error(self):
        if self._errors < self.MAX_ERROR_COUNT:
            self._errors += 1
        self._skip_to = self._errors * self.WAIT_ON_ERROR + time.time()

    @property
    def is_skip(self) -> bool:
        return self._errors and time.time() < self._skip_to


def _get_boot_time() -> int:
    try:
        with open('/proc/stat') as fp:
            for line in fp:
                if line.startswith('btime'):
                    return int(line.split()[1])
    except (IOError, IndexError, ValueError):
        pass
    return int(time.time())
