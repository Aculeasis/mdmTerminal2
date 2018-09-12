#!/usr/bin/env python3

import requests


class Error(Exception):
    def __init__(self, code, msg):
        self.code = code
        self.msg = msg


class TTS:
    TTS_URL = "{}/say"

    def __init__(self, text, url='http://127.0.0.1:8080', voice='anna', format_='mp3'):
        self._url = self.TTS_URL.format(url)
        self.__params = {
            'text': text,
            'voice': voice,
            'format': format_
        }
        self._data = None
        self._generate()

    def _generate(self):
        try:
            rq = requests.get(self._url, params=self.__params, stream=True)
        except (requests.exceptions.HTTPError, requests.exceptions.RequestException) as e:
            raise Error(code=1, msg=str(e))

        code = rq.status_code
        if code != 200:
            raise Error(code=code, msg='http code != 200')
        self._data = rq.iter_content

    def save(self, file_path, cb=None, after=0):
        if self._data is None:
            raise Exception('There\'s nothing to save')

        count = 0
        with open(file_path, 'wb') as f:
            for chunk in self._data(chunk_size=1024):
                f.write(chunk)
                if cb:
                    count += 1
                    if count == after:
                        cb()
                        cb = None
        return file_path


if __name__ == '__main__':
    test = TTS(text='Привет мир! 1 2 3.')
    test.save('test.mp3')
    print('test.mp3 generated!')

