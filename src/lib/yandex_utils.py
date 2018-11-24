#!/usr/bin/env python3

import time

import requests

from utils import REQUEST_ERRORS
from .proxy import proxies

KEY_LIFETIME = 11 * 3600


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
        data = None
    if data and 'error_code' in data:
        raise RuntimeError('[{}]{}: {}'.format(reply.status_code, data.get('error_code'), data.get('error_message')))
    if not reply.ok:
        raise RuntimeError('{}: {}'.format(reply.status_code, reply.reason))
    if key not in data:
        raise RuntimeError('Key \'{}\' not in reply'.format(key))
    return data[key]


def _aim_from_oauth(oauth):
    # https://cloud.yandex.ru/docs/iam/operations/iam-token/create
    # Получаем токен по токену, токен живет 12 часов.
    url = 'https://iam.api.cloud.yandex.net/iam/v1/tokens'
    params = {'yandexPassportOauthToken': oauth}
    key = 'iamToken'
    return requests_post(url, key, json=params, proxies=proxies('key_yandex'))


def get_key(key, api=1):
    key = key or ''
    if api != 2:
        return _cache(key, 1)
    key = key.split(':', 1)
    if len(key) != 2:
        raise RuntimeError('Wrong key for Yandex APIv2, must be \'<folderId>:<OAuth>\'')
    return key[0], _cache(key[1], 2)


# noinspection PyDefaultArgument
def _cache(key, api, cache__={}):
    # Кэширует старые халявные ключи и новые aim на 11 часов
    if key in cache__ and cache__[key][1] > time.time():
        return cache__[key][0]
    if api != 2:
        api_key = _get_api_key_v1()
    else:
        api_key = _aim_from_oauth(key)
    cache__[key] = (api_key, time.time() + KEY_LIFETIME)
    return api_key


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
