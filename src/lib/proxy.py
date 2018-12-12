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


class _Proxies:
    def __init__(self):
        self._proxy_raw = dict()
        self._params = dict()

        self._back_up = socket.socket
        self._patched = 0
        self._locker = threading.Lock()
        self._monkey_patching = False

        self._logger = print

    def monkey_patching_enable(self, key):
        if not self._monkey_patching:
            return
        kwargs, to_log = self._get_proxy_monkey(key)
        if not kwargs:
            return
        with self._locker:
            self._patched += 1
            if self._back_up == socket.socket:
                self._logger('enable {} for \'{}\' ...'.format(to_log, key))
                socks.set_default_proxy(**kwargs)
                socket.socket = socks.socksocket

    def monkey_patching_disable(self):
        if not self._monkey_patching:
            return
        with self._locker:
            self._patched -= 1
            if self._back_up != socket.socket and not self._patched:
                self._logger('disable.')
                socks.set_default_proxy()
                socket.socket = self._back_up

    def __call__(self, key, quiet=False):
        (data, to_log) = self._proxies(key)
        if not data:
            return
        if not quiet:
            self._logger('\'{}\' use {}'.format(key, to_log))
        return data

    def configure(self, cfg_: dict):
        with self._locker:
            cfg = cfg_.copy()

            self._proxy_raw.clear()
            self._params.clear()

            self._monkey_patching = cfg.pop('monkey_patching', True)

            for key, val in cfg.items():
                if key in PARAMS:
                    self._params[key] = _param_cleaning(val)
                else:
                    self._proxy_raw[key] = val
            # clear proxies cache
            self._get_proxy_monkey.cache_clear()
            self._proxies.cache_clear()

    def add_logger(self, log):
        self._logger = log

    @lru_cache()
    def _get_proxy_monkey(self, key):
        data = self._get_proxy_by_args(PROXIES[key])
        if not data:
            return None, None
        (data, to_log) = data
        data['rdns'] = data['proxy_type'] != 'socks5'
        data['proxy_type'] = data['proxy_type'] if data['proxy_type'] != 'socks5h' else 'socks5'
        data['proxy_type'] = socks.PROXY_TYPES[data['proxy_type'].upper()]
        return data, to_log

    @lru_cache()
    def _proxies(self, key):
        data = self._get_proxy_by_args(PROXIES[key])
        if not data:
            return None, None
        (data, to_log) = data
        auth = ''
        if 'username' in data:
            auth = '{}:{}@'.format(data['username'], data['password'])
        proxy = '{}://{}{}:{}'.format(data['proxy_type'], auth, data['addr'], data['port'])
        return {'http': proxy, 'https': proxy}, to_log

    def _get_proxy_index(self, args):
        index = None
        if args:
            for arg in args:
                if arg in self._params:
                    index = self._params[arg]
                    break
        return index if index is not None else self._params.get('enable', 0)

    def _get_proxy_by_args(self, args):
        index = self._get_proxy_index(args)
        if not index:
            return
        index = str(index) if index > 1 else ''
        params = self._get_proxy_by_index_compact(index)
        if not params:
            params = self._get_proxy_by_index(index)
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

    def _get_proxy_by_index(self, index: str):
        params = {x: self._proxy_raw.get(x + index) for x in PROXY_SET}
        if not _proxy_fill_checker(params):
            return
        return params

    def _get_proxy_by_index_compact(self, index: str):
        proxy = self._proxy_raw.get('proxy' + index)
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
            self._logger(e, ERROR)
            return
        if not _proxy_fill_checker(params):
            return
        return params


proxies = _Proxies()
