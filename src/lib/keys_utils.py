#!/usr/bin/env python3

import threading
import time
import urllib.parse
import requests

from utils import REQUEST_ERRORS, RuntimeErrorTrace, singleton, mask_off, PrettyException, yandex_cloud_reply_check
from .proxy import proxies
from .sr_wrapper import UnknownValueError

AZURE_ACCESS_ENDPOINT = 'https://{}.api.cognitive.microsoft.com/sts/v1.0/issueToken'


@singleton
class YandexSessionStorage:
    URL = 'https://cloud.yandex.ru/services/speechkit'
    XSRF = 'XSRF-TOKEN'
    CSRF = 'x-csrf-token'
    MAX_AGE = 86400

    def __init__(self):
        self._cookies, self._csrf_token, self._time = None, None, 0
        self._lock = threading.Lock()

    @property
    def requests_options(self) -> dict:
        with self._lock:
            if not self._cookies:
                raise RuntimeError('cookies is a None')
            if not self._csrf_token:
                raise RuntimeError('{} is a None'.format(self.CSRF))
            return {
                'cookies': self._cookies,
                'headers': {'Referer': self.URL, 'x-csrf-token': self._csrf_token},
            }

    def update(self, rq=None):
        with self._lock:
            time_ = time.time()
            get = rq is None
            try:
                if rq is None and (time_ - self._time) >= self.MAX_AGE:
                    rq = requests.get(self.URL, proxies=proxies('key_yandex'))
                if rq:
                    self._update(rq, time_)
            except Exception as e:
                self._clear()
                msg = 'Session get error: {}' if get else 'Session update error: {}'
                raise RuntimeError(msg.format(PrettyException(e)))

    def _update(self, rq, time_):
        yandex_cloud_reply_check(rq)
        try:
            self._cookies = rq.cookies
            token = self._cookies.get(self.XSRF)
            if not token:
                raise RuntimeError('{} not found in cookies'.format(self.XSRF))
            self._csrf_token = urllib.parse.unquote(token, errors='strict')
        except Exception as e:
            raise RuntimeError(e)
        self._time = time_

    def _clear(self):
        self._cookies, self._csrf_token, self._time = None, None, 0


@singleton
class Keystore:
    # Кэширует старые халявные ключи на 11 часов
    YANDEX_LIFETIME = 11 * 3600
    # ключи azure живут 10 минут
    AZURE_LIFETIME = 595

    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()

    def azure(self, key, region):
        key = (key, region)
        with self._lock:
            if key not in self._cache or self._cache[key][1] < time.time():
                self._cache[key] = (_azure_token_from_oauth(*key), time.time() + self.AZURE_LIFETIME)
            return self._cache[key][0], region

    def yandex_v1_free(self) -> str:
        key = 'yandex_v1_free'
        with self._lock:
            if key not in self._cache or self._cache[key][1] < time.time():
                self._cache[key] = (_yandex_get_api_key_v1(), time.time() + self.YANDEX_LIFETIME)
            return self._cache[key][0]

    def clear(self):
        with self._lock:
            self._cache.clear()


def requests_post(url, key: str, **kwargs):
    try:
        reply = requests.post(url, **kwargs)
    except REQUEST_ERRORS as e:
        raise RuntimeErrorTrace(e)
    try:
        data = reply.json()
    except ValueError as e:
        if reply.ok:
            raise RuntimeError('Error json parsing: {}'.format(e))
        data = {}
    if 'error_code' in data:
        raise RuntimeError('[{}]{}: {}'.format(reply.status_code, data.get('error_code'), data.get('error_message')))
    if not reply.ok:
        raise RuntimeError('{}: {}'.format(reply.status_code, reply.reason))
    if key not in data:
        raise RuntimeError('Key \'{}\' not in reply'.format(mask_off(key)))
    return data[key]


def xml_yandex(data):
    # https://tech.yandex.ru/speechkit/cloud/doc/guide/common/speechkit-common-asr-http-response-docpage/
    success_shift = 9
    variant_len = 10
    text = ''
    end_point = 0
    success_found = False
    for test in data.split('\n'):
        if success_found:
            end_point = test.rfind('</variant>')
            if end_point > 0:
                text = test
                break
        else:
            start_success = test.find('success="') + success_shift
            if start_success > success_shift:
                success_str = test[start_success:start_success+1]
                if success_str == '1':
                    success_found = True
                elif success_str == '0':
                    raise UnknownValueError('No variants')
                else:
                    raise RuntimeError('xml: root attribute broken - \'{}\''.format(success_str))

    if not success_found:
        raise RuntimeError('xml: root attribute not found, not XML?')

    start_variant = text.find('>') + 1
    if start_variant < variant_len or start_variant > end_point:
        raise RuntimeError('xml: broken XML')
    text = text[start_variant:end_point]
    return text


def _azure_token_from_oauth(key, region):
    # https://docs.microsoft.com/en-us/azure/cognitive-services/Speech-Service/rest-apis#authentication
    url = AZURE_ACCESS_ENDPOINT.format(region)
    headers = {
        'Ocp-Apim-Subscription-Key': key,
        'Content-type': 'application/x-www-form-urlencoded',
        'Content-Length': '0'
    }
    try:
        response = requests.post(url, headers=headers, proxies=proxies('token_azure'))
    except REQUEST_ERRORS as e:
        raise RuntimeErrorTrace(e)
    if not response.ok:
        raise RuntimeError('{}: {}'.format(response.status_code, response.reason))
    token = response.text
    if not token:
        raise RuntimeError('Azure send empty token')
    return token


def _yandex_get_api_key_v1():
    url = 'https://translate.yandex.com'
    target = 'SPEECHKIT_KEY:'

    try:
        response = requests.get(url, proxies=proxies('key_yandex'))
    except REQUEST_ERRORS as e:
        raise RuntimeErrorTrace(e)
    line = response.text
    if line.find('<title>Oops!</title>') > -1:
        raise RuntimeError('Yandex blocked automated requests')
    end = 0
    start = line.find(target)
    if start:
        start += len(target)
        end = line.find(',', start)
    if start and end and start < end:
        return line[start:end].strip(' \'')
    else:
        raise RuntimeError('API Key not extracted. Yandex change page?')
