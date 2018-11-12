
import subprocess
from shlex import quote

import requests
from bs4 import BeautifulSoup

from utils import REQUEST_ERRORS
from .proxy import proxies
from .stream_gTTS import gTTS as Google

__all__ = ['support', 'GetTTS', 'Google', 'Yandex', 'RHVoiceREST', 'RHVoice']


class BaseTTS:
    BUFF_SIZE = 1024

    def __init__(self, url, proxy_args=None, **kwargs):
        self._url = url
        self._params = kwargs.copy()
        self._data = None
        self._rq = None

        self._request_check()
        self._request(proxy_args)
        self._reply_check()

    def _request_check(self):
        if not self._params.get('text'):
            raise RuntimeError('No text to speak')

    def _request(self, proxy_args):
        try:
            self._rq = requests.get(
                self._url,
                params=self._params,
                stream=True,
                timeout=30,
                proxies=proxies(proxy_args)
            )
        except REQUEST_ERRORS as e:
            raise RuntimeError(str(e))
        self._data = self._rq.iter_content

    def _reply_check(self):
        if not self._rq.ok:
            msg = BeautifulSoup(self._rq.text, features='html.parser').text.replace('\n', ' ')[:99]
            raise RuntimeError('{}: {}'.format(self._rq.status_code, msg))

    def iter_me(self):
        if self._data is None:
            raise RuntimeError('No data')
        try:
            for chunk in self._data(chunk_size=self.BUFF_SIZE):
                yield chunk
        except REQUEST_ERRORS as e:
            raise RuntimeError(e)

    def stream_to_fps(self, fps):
        if not isinstance(fps, list):
            fps = [fps]
        for chunk in self.iter_me():
            for f in fps:
                f.write(chunk)

    def save(self, file_path):
        with open(file_path, 'wb') as fp:
            self.stream_to_fps(fp)
        return file_path


class Yandex(BaseTTS):
    URL = 'https://tts.voicetech.yandex.net/generate'
    MAX_CHARS = 2000

    def __init__(self, text, speaker, audio_format, key, emotion, lang, *_, **__):
        proxy_args = ('yandex_tts', 'yandex')
        super().__init__(self.URL, proxy_args, text=text, speaker=speaker or 'alyss',
                         format=audio_format, key=key, lang=lang or 'ru-RU', emotion=emotion or 'good')

    def _request_check(self):
        super()._request_check()
        if len(self._params['text']) >= self.MAX_CHARS:
            raise RuntimeError('Number of characters must be less than 2000')


class RHVoiceREST(BaseTTS):
    def __init__(self, text, speaker, audio_format, url, sets, *_, **__):
        proxy_args = ('rhvoice-rest',)
        super().__init__('{}/say'.format(url or 'http://127.0.0.1:8080'), proxy_args,
                         text=text, format=audio_format, voice=speaker or 'anna', **sets)


class RHVoice(RHVoiceREST):
    CMD = {
        'mp3': 'echo {} | RHVoice-test -p {} -o - | lame -ht -V 4 - -',
        'wav': 'echo {} | RHVoice-test -p {} -o -'
    }

    def _request(self, *_):
        self._rq = subprocess.Popen(
            self.CMD[self._params['format']].format(quote(self._params['text']), self._params['voice']),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True
        )
        self._data = self._rq.stdout
        self.__test = self._data.read(self.BUFF_SIZE)  # Ждем запуска, иначе poll() не вернет ошибку

    def _reply_check(self):
        if self._rq.poll():
            raise RuntimeError('{}: {}'.format(self._rq.poll(), ' '.join(self._rq.stderr.read().decode().split())[:99]))

    def iter_me(self):
        if self._data is None:
            raise RuntimeError('No data')
        if self.__test:
            yield self.__test
        while True:
            chunk = self._data.read(self.BUFF_SIZE)
            if not chunk:
                break
            yield chunk


_CLASS_BY_NAME = {'google': Google, 'yandex': Yandex, 'rhvoice-rest': RHVoiceREST, 'rhvoice': RHVoice}


def support(name):
    return name in _CLASS_BY_NAME


def GetTTS(name, **kwargs):
    if not support(name):
        raise RuntimeError('TTS {} not found'.format(name))
    return _CLASS_BY_NAME[name](**kwargs)
