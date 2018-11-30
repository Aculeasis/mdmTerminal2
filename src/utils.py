#!/usr/bin/env python3

import os
import queue
import signal
import socket
import threading
import time

import requests
import socks  # install socks-proxy dependencies - pip install requests[socks]
import urllib3

_PROXY_ERROR = socks.GeneralProxyError, socks.ProxyConnectionError, socks.SOCKS5AuthError, \
               socks.SOCKS5Error, socks.SOCKS4Error, socks.HTTPError
REQUEST_ERRORS = (
    requests.exceptions.HTTPError, requests.exceptions.RequestException, urllib3.exceptions.NewConnectionError,
    requests.exceptions.ChunkedEncodingError
) + _PROXY_ERROR


class UnknownValueError(Exception):
    pass


class SignalHandler:
    def __init__(self, signals=(signal.SIGTERM,)):
        self._sleep = threading.Event()
        self._death_time = 0
        [signal.signal(signal_, self._signal_handler)for signal_ in signals]

    def _signal_handler(self, *_):
        self._sleep.set()

    def die_in(self, sec: int):
        self._death_time = sec
        self._sleep.set()

    def interrupted(self) -> bool:
        return self._sleep.is_set()

    def sleep(self, sleep_time):
        self._sleep.wait(sleep_time)
        if self._death_time:
            time.sleep(self._death_time)


class FakeFP(queue.Queue):
    def read(self, _=None):
        return self.get()

    def write(self, n):
        self.put_nowait(n)

    def close(self):
        self.write(b'')


class EnergyControl:
    def __init__(self, cfg, play, default=700):
        self._cfg = cfg
        self._noising = play.noising
        self._energy_previous = default
        self._energy_currently = None
        self._lock = threading.Lock()

    def _energy_threshold(self):
        return self._cfg.gts('energy_threshold', 0)

    def correct(self, r, source):
        with self._lock:
            energy_threshold = self._energy_threshold()
            if energy_threshold > 0:
                r.energy_threshold = energy_threshold
                return None
            elif energy_threshold == -1 and self._energy_currently:
                r.energy_threshold = self._energy_currently
            elif energy_threshold == -1 and self._noising():
                # Не подстаиваем автоматический уровень шума если терминал шумит сам.
                # Пусть будет прошлое успешное значение или 700
                r.energy_threshold = self._energy_previous
            else:
                r.adjust_for_ambient_noise(source)
            return r.energy_threshold

    def set(self, energy_threshold):
        with self._lock:
            if self._energy_currently:
                self._energy_previous = self._energy_currently
            self._energy_currently = energy_threshold


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


def check_phrases(phrases):
    if phrases is None:
        return
    if not isinstance(phrases, dict):
        raise ValueError('Not a dict - {}'.format(type(phrases)))
    keys = ['hello', 'deaf', 'ask']
    for key in keys:
        if not isinstance(phrases.get(key), list):
            raise ValueError('{} must be list, not a {}'.format(key, type(phrases.get(key))))
        if not phrases[key]:
            raise ValueError('{} empty'.format(key))
    if not isinstance(phrases.get('chance'), int):
        raise ValueError('chance must be int type, not a {}'.format(type(phrases.get('chance'))))
    if phrases['chance'] < 0:
        raise ValueError('chance must be 0 or greater, not a {}'.format(phrases['chance']))
