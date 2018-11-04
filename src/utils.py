#!/usr/bin/env python3

import os
import queue
import signal
import socket
import subprocess
import threading
import time

import requests
import urllib3

REQUEST_ERRORS = (
    requests.exceptions.HTTPError, requests.exceptions.RequestException, urllib3.exceptions.NewConnectionError,
    requests.exceptions.ChunkedEncodingError
)

YANDEX_EMOTION = {
    'good'    : 'добрая',
    'neutral' : 'нейтральная',
    'evil'    : 'злая',
}

YANDEX_SPEAKER = {
    'jane'  : 'Джейн',
    'oksana': 'Оксана',
    'alyss' : 'Алиса',
    'omazh' : 'Дура',  # я это не выговорю
    'zahar' : 'Захар',
    'ermil' : 'Саня'  # и это
}

RHVOICE_SPEAKER = {
    'anna'     : 'Аня',
    'aleksandr': 'Александр',
    'elena'    : 'Елена',
    'irina'    : 'Ирина'
}


class SlowDead(threading.Thread):
    def __init__(self, callback):
        super().__init__(name='SlowDead')
        self._cb = callback
        self._death_time = 0
        self._work = True
        self.start()

    def die_in(self, sec: int):
        self._death_time = int(time.time()) + sec

    def stop(self):
        self._work = False
        self.join()

    def run(self):
        while self._work:
            time.sleep(1)
            if self._death_time and time.time() > self._death_time and self._work:
                self._death_time = 0
                self._cb()


class SignalHandler:
    SUPPRESS_SIGNAL = 0.2

    def __init__(self, signals=(signal.SIGTERM,), self_healing: bool =False):
        self._healing = self_healing
        self._sleep = threading.Event()
        self._reg_signals(signals)
        self._sd = SlowDead(self._signal_handler)
        self.stop = self._sd.stop
        self.die_in = self._sd.die_in

    def _reg_signals(self, signals):
        for x in signals:
            signal.signal(x, self._signal_handler)

    def _signal_handler(self, *_):
        self._sleep.set()

    def interrupted(self) -> bool:
        if self._healing and self._sleep.is_set():
            self._sleep.clear()
            return True
        return self._sleep.is_set()

    def sleep(self, sleep_time):
        if not self._sleep.is_set():
            self._sleep.wait(sleep_time)
        elif self._healing:
            time.sleep(self.SUPPRESS_SIGNAL)


class FakeFP(queue.Queue):
    def read(self, _=None):
        return self.get()

    def write(self, n):
        self.put_nowait(n)

    def close(self):
        self.write(b'')


class StreamPlayer(threading.Thread):
    def __init__(self, cmd: list, fp):
        super().__init__()
        self._fp = fp
        self._popen = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.poll = self._popen.poll
        self.start()

    def wait(self, timeout=None):
        try:
            self._popen.wait(timeout)
        finally:
            self._fp.write(b'')

    def kill(self):
        self._fp.write(b'')
        self._popen.kill()

    def run(self):
        data = self._fp.read()
        while data and self.poll() is None:
            try:
                self._popen.stdin.write(data)
            except BrokenPipeError:
                break
            data = self._fp.read()
        try:
            self._popen.stdin.close()
        except BrokenPipeError:
            pass
        try:
            self._popen.stderr.close()
        except BrokenPipeError:
            pass


def get_ip_address():
    s = socket.socket(type=socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    return s.getsockname()[0]


def is_int(test: str) -> bool:
    return test.lstrip('-').isdigit()


def pretty_time(sec) -> str:
    ends = ['sec', 'ms']  # , 'ns']
    max_index = len(ends) - 1
    index = 0
    while sec < 1 and index < max_index and sec:
        sec *= 1000
        index += 1
    sec = int(sec) if sec % 1 < 0.01 else round(sec, 2)
    return '{} {}'.format(sec, ends[index])


def pretty_size(size) -> str:
    ends = ['Bytes', 'KiB', 'MiB', 'GiB', 'TiB']
    max_index = len(ends) - 1
    index = 0
    while size >= 1024 and index < max_index:
        size /= 1024.0
        index += 1
    size = int(size) if size % 1 < 0.1 else round(size, 1)
    return '{} {}'.format(size, ends[index])


def write_permission_check(path):
    return os.access(os.path.dirname(os.path.abspath(path)), os.W_OK)


def rhvoice_rest_sets(data: dict):
    ignore = 50
    sets = {}
    for param in ['rate', 'pitch', 'volume']:
        val = data.get(param, ignore)
        if val != ignore:
            sets[param] = val
    return sets
