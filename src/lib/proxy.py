import socket
import threading
import urllib.parse
from functools import lru_cache

import socks

from logger import ERROR

PROXIES = {
    'tts_google': ('google_tts', 'google'),
    'tts_yandex': ('yandex_tts', 'yandex'),
    'tts_aws': ('aws',),
    'tts_rhvoice-rest': ('rhvoice-rest',),
    'stt_google': ('google_stt', 'google'),
    'stt_yandex': ('yandex_stt', 'yandex'),
    'stt_pocketsphinx-rest': ('pocketsphinx-rest',),
    'stt_wit.ai': ('wit.ai',),
    'stt_microsoft': ('microsoft',),
    'token_google': ('google_token', 'google_tts', 'google'),
    'key_yandex': ('yandex_token', 'yandex'),
    'snowboy_training': ('snowboy',),
}
PARAMS = frozenset(['enable'] + [_val_ for _key_ in PROXIES for _val_ in PROXIES[_key_]])
PROXY_SET = ('proxy_type', 'addr', 'port', 'username', 'password')
PROXY_TYPE = ('socks5', 'socks5h', 'http')

_proxy_raw = dict()
_params = dict()

_back_up = socket.socket
_patched = 0
_locker = threading.Lock()
_monkey_patching = False

_logger = print


def monkey_patching_enable(key):
    if not _monkey_patching:
        return
    global _patched, _locker
    kwargs, to_log = _get_proxy_monkey(key)
    if not kwargs:
        return
    with _locker:
        _patched += 1
        if _back_up == socket.socket:
            _logger('enable {} for \'{}\' ...'.format(to_log, key))
            socks.set_default_proxy(**kwargs)
            socket.socket = socks.socksocket


def monkey_patching_disable():
    if not _monkey_patching:
        return
    global _patched, _locker
    with _locker:
        _patched -= 1
        if _back_up != socket.socket and not _patched:
            _logger('disable.')
            socks.set_default_proxy()
            socket.socket = _back_up


def proxies(key, quiet=False):
    (data, to_log) = _proxies(key)
    if not data:
        return
    if not quiet:
        _logger('\'{}\' use {}'.format(key, to_log))
    return data


def setting(cfg_: dict):
    cfg = cfg_.copy()
    global _proxy_raw, _params, _monkey_patching

    _proxy_raw.clear()
    _params.clear()
    _get_proxy_monkey.cache_clear()
    _proxies.cache_clear()

    _monkey_patching = cfg.pop('monkey_patching', 1)

    for key, val in cfg.items():
        if key in PARAMS:
            _params[key] = _param_cleaning(val)
        else:
            _proxy_raw[key] = val


def add_logger(log):
    global _logger
    _logger = log


@lru_cache()
def _get_proxy_monkey(key):
    data = _get_proxy_by_args(PROXIES[key])
    if not data:
        return None, None
    (data, to_log) = data
    data['rdns'] = data['proxy_type'] != 'socks5'
    data['proxy_type'] = data['proxy_type'] if data['proxy_type'] != 'socks5h' else 'socks5'
    data['proxy_type'] = socks.PROXY_TYPES[data['proxy_type'].upper()]
    return data, to_log


@lru_cache()
def _proxies(key):
    data = _get_proxy_by_args(PROXIES[key])
    if not data:
        return None, None
    (data, to_log) = data
    auth = ''
    if 'username' in data:
        auth = '{}:{}@'.format(data['username'], data['password'])
    proxy = '{}://{}{}:{}'.format(data['proxy_type'], auth, data['addr'], data['port'])
    return {'http': proxy, 'https': proxy}, to_log


def _get_proxy_index(args):
    index = None
    if args:
        for arg in args:
            if arg in _params:
                index = _params[arg]
                break
    return index if index is not None else _params.get('enable', 0)


def _get_proxy_by_args(args):
    index = _get_proxy_index(args)
    if not index:
        return
    index = str(index) if index > 1 else ''
    params = _get_proxy_by_index_compact(index)
    if not params:
        _get_proxy_by_index(index)
    if not params:
        return
    auth = 'user:pass@'
    if not (params['username'] and params['password']):
        params.pop('username')
        params.pop('password')
        auth = ''
    proxy_id = '' if not index else '[{}]:'.format(index)
    to_log = '{}{}://{}{}:{}'.format(proxy_id, params['proxy_type'], auth, params['addr'], params['port'])
    return params, to_log


def _get_proxy_by_index(index: str):
    params = {x: _proxy_raw.get(x + index) for x in PROXY_SET}
    if not _proxy_fill_checker(params):
        return
    return params


def _get_proxy_by_index_compact(index: str):
    proxy = _proxy_raw.get('proxy' + index)
    if not (proxy and isinstance(proxy, str)):
        return
    pr = urllib.parse.urlparse(proxy)
    try:
        params = {
            'proxy_type': pr.scheme,
            'addr': pr.hostname,
            'port': pr.port,
            'username': pr.password,
            'password': pr.password,
        }
    except ValueError as e:
        _logger(e, ERROR)
        return
    if not _proxy_fill_checker(params):
        return
    return params


def _proxy_fill_checker(params: dict):
    if not (params['proxy_type'] and params['addr'] and params['port']):
        return False
    if params['proxy_type'] not in PROXY_TYPE:
        return False
    return True


def _param_cleaning(param):
    index = 1 if param else 0
    try:
        index = int(param)
    except ValueError:
        pass
    else:
        if index < 0:
            index = 0
    return index
