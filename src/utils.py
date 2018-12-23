#!/usr/bin/env python3

import functools
import os
import queue
import signal
import socket
import subprocess
import threading
import time
import traceback

import requests
import socks  # install socks-proxy dependencies - pip install requests[socks]
import urllib3

from languages import YANDEX_SPEAKER, RHVOICE_SPEAKER, AWS_SPEAKER, DEFAULT_SPEAKERS

REQUEST_ERRORS = (
    requests.exceptions.HTTPError, requests.exceptions.RequestException, urllib3.exceptions.NewConnectionError,
    socks.ProxyError
)


class RuntimeErrorTrace(RuntimeError):
    def __init__(self, *args):
        super().__init__('{}: {}'.format(' '.join([repr(arg) for arg in args]), traceback.format_exc()))


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
    def __init__(self, cfg, noising, default=700):
        self._cfg = cfg
        self._noising = noising
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
            elif energy_threshold < 0 and self._energy_currently:
                r.energy_threshold = self._energy_currently
            elif energy_threshold < 0 and self._noising():
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


class Popen:
    TIMEOUT = 3 * 3600

    def __init__(self, cmd):
        self._cmd = cmd
        self._popen = None

    def _close(self):
        if self._popen:
            for target in (self._popen.stderr, self._popen.stdout):
                try:
                    target.close()
                except BrokenPipeError:
                    pass

    def run(self):
        try:
            return self._run()
        finally:
            self._close()

    def _run(self):
        try:
            self._popen = subprocess.Popen(self._cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        except FileNotFoundError as e:
            raise RuntimeError(e)
        try:
            self._popen.wait(self.TIMEOUT)
        except subprocess.TimeoutExpired as e:
            self._popen.kill()
            raise RuntimeError(e)
        if self._popen.poll():
            raise RuntimeError('{}: {}'.format(self._popen.poll(), repr(self._popen.stderr.read().decode())))
        return self._popen.stdout.read().decode()


def fix_speakers(cfg: dict) -> bool:
    modify = False
    for name, speakers in (
            ('rhvoice', RHVOICE_SPEAKER),
            ('rhvoice-rest', RHVOICE_SPEAKER),
            ('yandex', YANDEX_SPEAKER),
            ('aws', AWS_SPEAKER)):
        if not isinstance(cfg.get(name), dict) or 'speaker' not in cfg[name]:
            continue
        if cfg[name]['speaker'] in speakers:
            continue
        def_name = name if name != 'rhvoice-rest' else 'rhvoice'
        if def_name in DEFAULT_SPEAKERS:
            cfg[name]['speaker'] = DEFAULT_SPEAKERS[def_name]
            modify = True
    return modify


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


def timed_cache(**timedelta_kwargs):
    """Кэширует результат вызова с учетом параметров на interval"""
    # https://gist.github.com/Morreski/c1d08a3afa4040815eafd3891e16b945
    def _wrapper(f):
        maxsize = timedelta_kwargs.pop('maxsize', 128)
        typed = timedelta_kwargs.pop('typed', False)
        update_delta = timedelta_kwargs.pop('interval', 1.0)
        next_update = time.time() - update_delta
        # Apply @lru_cache to f
        f = functools.lru_cache(maxsize=maxsize, typed=typed)(f)

        @functools.wraps(f)
        def _wrapped(*args, **kwargs):
            nonlocal next_update
            now = time.time()
            if now >= next_update:
                f.cache_clear()
                next_update = now + update_delta
            return f(*args, **kwargs)
        return _wrapped
    return _wrapper


def state_cache(interval):
    """
    Кэширует результат вызова без учета параметров на interval
    Чуть быстрее чем timed_cache, актуально если вызовы очень частые
    """
    def _wrapper(f):
        update_interval = interval
        next_update = time.time() - update_interval
        state = None

        @functools.wraps(f)
        def _wrapped(*args, **kwargs):
            nonlocal next_update, state
            now = time.time()
            if now >= next_update:
                next_update = now + update_interval
                state = f(*args, **kwargs)
            return state
        return _wrapped
    return _wrapper


def bool_cast(value) -> bool:
    """Интерпретируем что угодно как bool или кидаем ValueError"""
    if isinstance(value, str):
        value = value.lower()
        if value in ('on', '1', 'true', 'yes', 'enable'):
            return True
        elif value in ('off', '0', 'false', 'no', 'disable'):
            return False
    elif isinstance(value, bool):
        return value
    elif isinstance(value, int) and value in (1, 0):
        return bool(value)
    raise ValueError('Wrong type or value')


def yandex_speed_normalization(speed):
    return min(3.0, max(0.1, speed))


def singleton(cls):
    instances = {}

    def get_instance():
        if cls not in instances:
            instances[cls] = cls()
        return instances[cls]

    return get_instance
