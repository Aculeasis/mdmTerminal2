#!/usr/bin/env python3

import queue
import threading
import time

import requests

import logger
from lib.outgoing_socket import OutgoingSocket
from owner import Owner
from utils import REQUEST_ERRORS, RuntimeErrorTrace


class MajordomoNotifier(threading.Thread):
    MAX_API_FAIL_COUNT = 10

    def __init__(self, cfg, log, owner: Owner):
        super().__init__(name='Notifier')
        self._cfg = cfg['smarthome']
        self.log = log
        self.own = owner
        self._work = False
        self._queue = queue.Queue()
        self._boot_time = None
        self._api_fail_count = self.MAX_API_FAIL_COUNT
        self._events = (
            'speech_recognized_success', 'voice_activated', 'ask_again',
            'music_status', 'start_record', 'stop_record', 'start_talking', 'stop_talking',
            'volume', 'music_volume',
            'updater',
        )
        self.outgoing = OutgoingSocket(self._cfg, log.add('O'), self.own)

    def _subscribe(self):
        # Подписываемся на нужные события, если нужно
        if self._allow_notify:
            self.own.subscribe(self._events, self._callback)

    def _unsubscribe(self):
        self.own.unsubscribe(self._events, self._callback)

    def reload(self, diff: dict):
        self._api_fail_count = self.MAX_API_FAIL_COUNT
        self._unsubscribe()
        self._subscribe()
        self._queue.put_nowait(None)
        if 'outgoing_socket' in diff.get('smarthome', {}):
            self.outgoing.reload()

    def start(self):
        self._work = True
        self.log('start', logger.INFO)
        self._subscribe()
        super().start()
        self.outgoing.start()

    def join(self, timeout=None):
        if self._work:
            self._work = False
            self._queue.put_nowait(None)
            self.log('stopping...', logger.DEBUG)
            super().join()
            self.outgoing.join(20)
            self.log('stop.', logger.INFO)

    def run(self):
        while self._work:
            to_sleep = self._cfg['heartbeat_timeout']
            if to_sleep <= 0:
                to_sleep = None
            try:
                data = self._queue.get(timeout=to_sleep)
            except queue.Empty:
                if not (self._allow_notify and self._api_fail_count and to_sleep):
                    continue
                # Отправляем пинг на сервер мжд
                data = self.own.get_volume_status
                data['uptime'] = self._uptime
            else:
                if not isinstance(data, dict):
                    continue
            self._send_notify(data)

    def send(self, qry: str, user=None) -> str:
        # Прямая отправка
        # Отправляет сообщение на сервер мжд, возвращает url запроса или кидает RuntimeError
        # На основе https://github.com/sergejey/majordomo-chromegate/blob/master/js/main.js#L196
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
        # Отправляет статус на сервер мжд в порядке очереди (FIFO)
        if not self._allow_notify:
            return
        kwargs = {'uptime': self._uptime}
        if name in ('volume', 'music_volume', 'updater'):
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
            self.log(e, logger.ERROR)
            self._api_fail_count -= 1
            if not self._api_fail_count:
                self._unsubscribe()
                msg = 'MajorDoMo API call failed {} times - notifications disabled.'.format(self.MAX_API_FAIL_COUNT)
                self.log(msg, logger.CRIT)
        else:
            self._api_fail_count = self.MAX_API_FAIL_COUNT

    def _send(self, target: str, params: dict, user=None) -> str:
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

    def _send_over_http(self, target: str, params: dict, auth: tuple or None) -> str:
        if self._cfg['disable_http']:
            return 'http disabled'
        elif target == 'api':
            path = 'api/method/{}.{}'.format(self._cfg['object_name'], self._cfg['object_method'])
        else:
            path = 'command.php'
        url = 'http://{}/{}'.format(self._cfg['ip'], path)
        try:
            reply = requests.get(url, params=params, auth=auth, timeout=30)
        except REQUEST_ERRORS as e:
            raise RuntimeErrorTrace(e)
        if not reply.ok:
            raise RuntimeError('Server reply error from \'{}\'. {}: {}'.format(url, reply.status_code, reply.reason))
        return reply.request.url

    def _send_over_socket(self, target: str, params: dict) -> str:
        self.own.send_on_duplex_mode({'method': target, 'params': params})
        return 'in socket {}: {}'.format(target, repr(params)[:300])


def _get_boot_time() -> int:
    try:
        with open('/proc/stat') as fp:
            for line in fp:
                if line.startswith('btime'):
                    return int(line.split()[1])
    except (IOError, IndexError, ValueError):
        pass
    return int(time.time())
