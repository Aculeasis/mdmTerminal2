#!/usr/bin/env python3

import base64
import errno
import functools
import json
import os
import queue
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import warnings
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
from functools import lru_cache

import requests
import socks  # install socks-proxy dependencies - pip install requests[socks]
import urllib3
from websocket import WebSocketException

REQUEST_ERRORS = (
    requests.exceptions.RequestException, urllib3.exceptions.NewConnectionError, socks.ProxyError, ssl.CertificateError,
    WebSocketException,
)


class TextBox(str):
    def __new__(cls, text, provider=None, time_=0):
        # noinspection PyArgumentList
        obj = str.__new__(cls, text)
        obj.provider = str(provider) if provider else ''
        obj.time = time_
        return obj


class _HashableDict:
    # noinspection PyTypeChecker
    def __hash__(self):
        return hash(self._cfg_as_tuple(self))

    def _cfg_as_tuple(self, data: dict) -> tuple:
        result = []
        for key, val in data.items():
            if not isinstance(key, str):
                continue
            elif isinstance(val, dict):
                result.append((key, self._cfg_as_tuple(val)))
            elif isinstance(val, (bool, str, int, float, bytes)) or val is None:
                result.append((key, val))
        result.sort()
        return tuple(result)


class HashableDict(_HashableDict, dict):
    pass


class HashableOrderedDict(_HashableDict, OrderedDict):
    pass


class RuntimeErrorTrace(RuntimeError):
    def __init__(self, *args):
        super().__init__('{},  Traceback: \n{}'.format(args, traceback.format_exc()))


class PrettyException(RuntimeError):
    def __init__(self, error: Exception):
        _, value, tb = sys.exc_info()
        frame = traceback.TracebackException(type(value), value, tb).stack[-1]
        path = frame.filename.split('src', 1)
        frame.filename = ''.join(('/src', path[1])) if len(path) == 2 and path[1] else frame.filename
        target = '{}#L{}'.format(frame.filename, frame.lineno)
        target = '{} in {}'.format(target, frame.name) if frame.name and frame.name != '<module>' else target
        super().__init__('{}: "{}" -> {}'.format(error.__class__.__name__, error, target))


class RecognitionCrashMessage(Exception):
    pass


class SignalHandlerDummy:
    def __init__(self, *_, **__):
        pass

    def set_wakeup_callback(self, wakeup):
        pass

    def die_in(self, sec: int):
        pass

    def interrupted(self) -> bool:
        pass

    def sleep(self, sleep_time):
        pass


class SignalHandler(SignalHandlerDummy):
    def __init__(self, signals=(signal.SIGTERM,)):
        super().__init__()
        self._sleep = threading.Event()
        self._death_time = 0
        self._wakeup = None
        [signal.signal(signal_, self._signal_handler) for signal_ in signals]

    def _signal_handler(self, _, __):
        self._sleep.set()

    def set_wakeup_callback(self, wakeup):
        self._wakeup = wakeup

    def die_in(self, sec: int):
        self._death_time = sec
        self._sleep.set()

    def interrupted(self) -> bool:
        return self._sleep.is_set()

    def sleep(self, sleep_time):
        self._sleep.wait(sleep_time)
        if self._wakeup:
            self._wakeup()
        if self._death_time:
            time.sleep(self._death_time)


class FakeFP(queue.Queue):
    def read(self, _=None):
        return self.get()

    def write(self, n):
        self.put_nowait(n)

    def close(self):
        self.write(b'')


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


class Messenger(threading.Thread):
    def __init__(self, call, callback, *args, **kwargs):
        super().__init__(name='Messenger')
        self.call = call if callable(call) else None
        self.callback = callback if callable(callback) else None
        self.args, self.kwargs = args, kwargs

    def __call__(self) -> bool:
        if not self.call:
            return False
        self.start()
        return True

    def run(self):
        result = self.call(*self.args, **self.kwargs)
        if self.callback:
            self.callback(result)


def is_valid_base_filename(filename: str) -> bool:
    if not (filename and isinstance(filename, str) and not filename.startswith(('.', '~'))):
        return False
    # check wrong chars
    wrong_chars = '*/:?"|+<>\n\r\t\n\0\\'
    return not set(wrong_chars).intersection(filename)


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
    while abs(sec) < 1 and index < max_index and sec:
        sec *= 1000
        index += 1
    sec = int(sec) if abs(sec) % 1 < 0.01 else round(sec, 2)
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


def yandex_cloud_reply_check(rq: requests.Response):
    if not rq.ok:
        try:
            data = rq.json()
        except ValueError:
            data = {}
        if 'error_code' in data:
            msg = '[{}]{}: {}'.format(rq.status_code, data.get('error_code'), data.get('error_message'))
        elif 'error' in data:
            msg = '[{}]: {}'.format(rq.status_code, data['error'])
        else:
            msg = '{}: {}'.format(rq.status_code, rq.reason)
        raise RuntimeError(msg)


def singleton(cls):
    instances = {}

    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance


def file_to_base64(file_name: str) -> str:
    with open(file_name, 'rb') as fp:
        return base64.b64encode(fp.read()).decode()


def base64_to_bytes(data):
    try:
        return base64.b64decode(data)
    except (ValueError, TypeError) as e:
        raise RuntimeError(e)


def mask_off(obj):
    base_mask = '*' * 6
    result = '**HIDDEN OBJECT**'
    if not obj:
        result = obj
    elif isinstance(obj, (list, tuple, set, dict)):
        result = [mask_off(key) for key in obj]
    elif isinstance(obj, bool):
        result = obj
    elif isinstance(obj, (int, float)):
        result = obj if len(str(obj)) < 3 else base_mask
    elif isinstance(obj, str):
        obj_len = len(obj)
        result = base_mask if obj_len < 14 else '{}**LENGTH<{}>**{}'.format(obj[:2], obj_len, obj[-2:])
    return result


def mask_cfg(cfg: dict) -> dict:
    """Маскируем значение ключей которые могут содержать приватную информацию"""
    privates = ('apikeystt', 'apikeytts', 'password', 'secret_access_key', 'token', 'ws_token')
    if not cfg:
        return cfg
    mask = deepcopy(cfg)
    for section in mask:
        if not isinstance(mask[section], dict):
            continue
        for key in mask[section]:
            if key in privates:
                mask[section][key] = mask_off(mask[section][key])
    return mask


def str_to_list(string: str, sep=',') -> list:
    if not (string and isinstance(string, str)):
        return []
    result = []
    for el in string.split(sep):
        el = el.strip()
        if el and el not in result:
            result.append(el)
    return result


def dict_from_file(file_path: str) -> dict:
    ext = os.path.splitext(file_path)[1]
    try:
        with open(file_path, encoding='utf8') as fp:
            if ext == '.json':
                return json.load(fp)
            elif ext == '.yml':
                import yaml
                try:
                    return yaml.safe_load(fp)
                except yaml.YAMLError as e:
                    raise RuntimeError(e)
            else:
                raise RuntimeError('Unknown format: {}'.format(ext))
    except (json.decoder.JSONDecodeError, TypeError, OSError) as e:
        raise RuntimeError(e)


def dict_to_file(file_path: str, data: dict, pretty: bool):
    indent = 4 if pretty else None
    ext = os.path.splitext(file_path)[1]
    try:
        with open(file_path, 'w', encoding='utf8') as fp:
            if ext == '.json':
                json.dump(data, fp, ensure_ascii=False, indent=indent)
            elif ext == '.yml':
                import yaml
                try:
                    return yaml.safe_dump(data, fp, allow_unicode=True)
                except yaml.YAMLError as e:
                    raise RuntimeError(e)
            else:
                raise RuntimeError('Unknown format: {}'.format(ext))
    except (TypeError, OSError) as e:
        raise RuntimeError(e)


@lru_cache(maxsize=32)
def url_builder_cached(url_ip: str, def_port='', def_proto='http', def_path='') -> str:
    return url_builder(url_ip, def_port, def_proto, def_path)


def url_builder(url_ip: str, def_port='', def_proto='http', def_path='') -> str:
    if not url_ip.startswith(('http://', 'https://', 'ws://')):
        # url:ip, url:ip/path
        url_ip = '{}://{}'.format(def_proto, url_ip)
    url = urllib.parse.urlparse(url_ip)
    scheme = url.scheme or def_proto
    hostname = url.hostname or url_ip
    path = url.path.rstrip('/') if url.hostname and url.path and url.path != '/' else def_path
    selected_port = url.port or def_port
    port = ':{}'.format(selected_port) if selected_port else ''
    return '{}://{}{}{}'.format(scheme, hostname, port, path)


def recognition_msg(msg, energy, rms) -> str:
    energy_str = '; energy_threshold: {}'.format(energy) if energy else ''
    rms_str = '; rms: {}'.format(rms) if rms else ''
    return 'Recognized: {}{}{}'.format(msg, energy_str, rms_str)


def server_init(sock: socket.socket, address: tuple, timeout):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass
    except socket.error as e:
        if e.errno != errno.ENOPROTOOPT:
            raise
    sock.bind(address)


def deprecated(func):
    """This is a decorator which can be used to mark functions
    as deprecated. It will result in a warning being emitted
    when the function is used."""
    @functools.wraps(func)
    def new_func(*args, **kwargs):
        warnings.simplefilter('always', DeprecationWarning)  # turn off filter
        warnings.warn("Call to deprecated function {}.".format(func.__name__),
                      category=DeprecationWarning,
                      stacklevel=2)
        warnings.simplefilter('default', DeprecationWarning)  # reset filter
        return func(*args, **kwargs)
    return new_func


@contextmanager
def file_lock(lockfile: str):
    try:
        if sys.platform == 'win32':
            os.path.isfile(lockfile) and os.unlink(lockfile)
            fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        else:
            # noinspection PyUnresolvedReferences
            import fcntl
            fd = open(lockfile, 'w')
            fd.flush()
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        print('mdmTerminal2 already running: ', lockfile)
        raise
    yield None
    try:
        os.close(fd) if sys.platform == 'win32' else fcntl.lockf(fd, fcntl.LOCK_UN)
        os.path.isfile(lockfile) and os.unlink(lockfile)
    except Exception:
        print('Error unlocked: ', lockfile)
        raise
