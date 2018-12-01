#!/usr/bin/env python3

import subprocess
import threading
import time

import requests

from utils import REQUEST_ERRORS, UnknownValueError
from .proxy import proxies


class Keystore:
    # Кэширует старые халявные ключи и новые aim на 11 часов
    KEY_LIFETIME = 11 * 3600

    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()

    def get(self, key, api: int=1):
        key = key or ''
        if api != 2:
            return self._storage(key, 1)
        key = key.split(':', 1)
        if len(key) != 2:
            raise RuntimeError('Wrong key for Yandex APIv2, must be \'<folderId>:<OAuth>\'')
        return key[0], self._storage(key[1], 2)

    def _storage(self, key, api):
        with self._lock:
            if key not in self._cache or self._cache[key][1] < time.time():
                self._cache[key] = (_get_key(key, api), time.time() + self.KEY_LIFETIME)
            return self._cache[key][0]

    def clear(self):
        with self._lock:
            self._cache.clear()


def requests_post(url, key: str, **kwargs):
    try:
        reply = requests.post(url, **kwargs)
    except REQUEST_ERRORS as e:
        raise RuntimeError(e)
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
        raise RuntimeError('Key \'{}\' not in reply'.format(key))
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


def _get_key(key, api):
    if api != 2:
        return _get_api_key_v1()
    else:
        return _aim_from_oauth(key)


def _aim_from_oauth(oauth):
    # https://cloud.yandex.ru/docs/iam/operations/iam-token/create
    # Получаем токен по токену, токен живет 12 часов.
    url = 'https://iam.api.cloud.yandex.net/iam/v1/tokens'
    params = {'yandexPassportOauthToken': oauth}
    key = 'iamToken'
    return requests_post(url, key, json=params, proxies=proxies('key_yandex'))


def _get_api_key_v1():
    url = 'https://translate.yandex.com'
    target = 'SPEECHKIT_KEY:'

    try:
        response = requests.get(url, proxies=proxies('key_yandex'))
    except REQUEST_ERRORS as e:
        raise RuntimeError(str(e))
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


def wav_to_opus(wav_data):
    process = subprocess.Popen(
        ['opusenc', '--quiet', '--discard-comments', '-', '-'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE)
    opus_data, _ = process.communicate(wav_data)
    return opus_data
