#!/usr/bin/env python3

import time

import requests

from utils import REQUEST_ERRORS
from .proxy import proxies


class APIKey:
    URL = 'https://translate.yandex.com'
    TARGET = 'SPEECHKIT_KEY:'
    LIFE_TIME = 12 * 60 * 60

    def __init__(self):
        self._api_key = None
        self._get_time = 0

    @property
    def key(self):
        if not self._api_key or self._rotten():
            self._extract()
        return self._api_key

    def _rotten(self):
        return time.perf_counter() > self._get_time + self.LIFE_TIME

    def _extract(self):
        try:
            response = requests.get(self.URL, proxies=proxies('key_yandex'))
        except REQUEST_ERRORS as e:
            raise RuntimeError(str(e))
        line = response.text
        if line.find('<title>Oops!</title>') > -1:
            raise RuntimeError('Yandex blocked automated requests')
        end = 0
        result = None
        start = line.find(self.TARGET)
        if start:
            start += len(self.TARGET)
            end = line.find(',', start)
        if start and end and start < end:
            result = line[start:end].strip(' \'')
        if result:
            self._get_time = time.perf_counter()
        else:
            raise RuntimeError('API Key not extracted. Yandex change page?')

        self._api_key = result


if __name__ == '__main__':
    print(APIKey().key)

