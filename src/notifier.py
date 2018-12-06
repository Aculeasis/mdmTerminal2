#!/usr/bin/env python3

import queue
import threading
import time

import requests

import logger
from utils import REQUEST_ERRORS


class MajordomoNotifier(threading.Thread):
    def __init__(self, cfg, log, get_volume):
        super().__init__(name='Notifier')
        self._cfg = cfg
        self.log = log
        self._get_volume = get_volume
        self._work = False
        self._queue = queue.Queue()
        self._boot_time = _get_boot_time()

    def start(self):
        self._work = True
        self.log('start', logger.INFO)
        super().start()

    def join(self, timeout=None):
        if self._work:
            self._work = False
            self._queue.put_nowait(None)
            self.log('stopping...', logger.DEBUG)
            super().join()
            self.log('stop.', logger.INFO)

    def run(self):
        while self._work:
            to_sleep = self._cfg['heartbeat_timeout']
            if to_sleep <= 0:
                to_sleep = None
            try:
                data = self._queue.get(timeout=to_sleep)
            except queue.Empty:
                # Отправляем пинг на сервер мжд
                volume = self._get_volume()
                volume['uptime'] = self.uptime
                self._send_notify(volume)
                continue
            if not isinstance(data, dict):
                continue
            self._send_notify(data)

    @property
    def ip_set(self) -> bool:
        return True if self._cfg.get('ip') else False

    def record_callback(self, start_stop: bool):
        # Отправляет статус на сервер мжд в порядке очереди (FIFO)
        self._queue.put_nowait({
            'status': 'start_record' if start_stop else 'stop_record',
            'uptime': self.uptime
        })

    def send(self, qry: str):
        # Прямая отправка
        # Отправляет сообщение на сервер мжд, возвращает url запроса или кидает RuntimeError
        # На основе https://github.com/sergejey/majordomo-chromegate/blob/master/js/main.js#L196
        return self._send('command.php', {'qry': qry})

    @property
    def uptime(self) -> int:
        # Считаем uptime от времени загрузки, так быстрее чем каждый раз дергать его из фс.
        return int(time.time() - self._boot_time)

    def _send_notify(self, params: dict):
        if self._cfg['object_name'] and self._cfg['object_method'] and self.ip_set:
            path = 'api/method/{}.{}'.format(self._cfg['object_name'], self._cfg['object_method'])
            try:
                self._send(path, params)
            except RuntimeError as e:
                self.log(e, logger.ERROR)

    def _send(self, path: str, params: dict) -> str:
        terminal = self._cfg.get('terminal')
        username = self._cfg.get('username')
        password = self._cfg.get('password')
        url = 'http://{}/{}'.format(self._cfg.get('ip', ''), path)

        auth = (username, password) if username and password else None
        if terminal:
            params['terminal'] = terminal
        if username:
            params['username'] = username
        try:
            reply = requests.get(url, params=params, auth=auth, timeout=30)
        except REQUEST_ERRORS as e:
            raise RuntimeError(e)
        if not reply.ok:
            raise RuntimeError('Request error {}: {}'.format(reply.status_code, reply.reason))
        return reply.request.url


def _get_boot_time() -> int:
    try:
        with open('/proc/stat') as fp:
            for line in fp:
                if line.startswith('btime'):
                    return int(line.split()[1])
        return int(time.time())
    except (IOError, IndexError, TypeError):
        return int(time.time())
