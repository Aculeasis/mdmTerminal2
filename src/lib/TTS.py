
import subprocess
from shlex import quote

import requests

from utils import REQUEST_ERRORS
from .gtts_proxifier import Google, gTTSError
from .polly_boto3 import aws_boto3
from .polly_signing import signing as polly_signing
from .proxy import proxies

__all__ = ['support', 'GetTTS', 'Google', 'Yandex', 'AWS', 'YandexCloud', 'RHVoiceREST', 'RHVoice', 'gTTSError']


class BaseTTS:
    MAX_CHARS = None

    def __init__(self, url, proxy_key=None, buff_size=1024, **kwargs):
        self._url = url
        self._buff_size = buff_size
        self._params = kwargs.copy()
        self._data = None
        self._rq = None

        self._request_check()
        self._request(proxy_key)
        self._reply_check()

    def _request_check(self):
        if not self._params.get('text'):
            raise RuntimeError('No text to speak')
        if self.MAX_CHARS and len(self._params['text']) >= self.MAX_CHARS:
            raise RuntimeError('Number of characters must be less than {}'.format(self.MAX_CHARS))

    def _request(self, proxy_key):
        try:
            self._rq = requests.get(
                self._url,
                params=self._params,
                stream=True,
                timeout=30,
                proxies=proxies(proxy_key)
            )
        except REQUEST_ERRORS as e:
            raise RuntimeError(str(e))
        self._data = self._rq.iter_content

    def _reply_check(self):
        if not self._rq.ok:
            raise RuntimeError('{}: {}'.format(self._rq.status_code, self._rq.reason))

    def iter_me(self):
        if self._data is None:
            raise RuntimeError('No data')
        try:
            for chunk in self._data(chunk_size=self._buff_size):
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
    # https://tech.yandex.ru/speechkit/cloud/doc/guide/common/speechkit-common-tts-http-request-docpage/
    URL = 'https://tts.voicetech.yandex.net/generate'
    MAX_CHARS = 2000

    def __init__(self, text, buff_size, speaker, audio_format, key, emotion, lang, *_, **__):
        super().__init__(self.URL, 'tts_yandex', buff_size=buff_size, text=text, speaker=speaker or 'alyss',
                         format=audio_format, key=key, lang=lang or 'ru-RU', emotion=emotion or 'good')


class YandexCloud(BaseTTS):
    # https://cloud.yandex.ru/docs/speechkit/tts/request
    URL = 'https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize'
    MAX_CHARS = 5000

    def __init__(self, text, buff_size, speaker, key, emotion, lang, *_, **__):
        if not isinstance(key, (tuple, list)) or len(key) < 2:
            raise RuntimeError('Wrong Yandex APIv2 key')
        self._headers = {'Authorization': 'Bearer {}'.format(key[1])}
        super().__init__(self.URL, 'tts_yandex', buff_size=buff_size, text=text, voice=speaker or 'alyss',
                         format='oggopus', folderId=key[0], lang=lang or 'ru-RU', emotion=emotion or 'good')

    def _request(self, proxy_key):
        try:
            self._rq = requests.post(
                self._url,
                data=self._params,
                headers=self._headers,
                stream=True,
                timeout=30,
                proxies=proxies(proxy_key)
            )
        except REQUEST_ERRORS as e:
            raise RuntimeError(str(e))
        self._data = self._rq.iter_content

    def _reply_check(self):
        if not self._rq.ok:
            try:
                data = self._rq.json()
            except ValueError:
                data = {}
            if 'error_code' in data:
                msg = '[{}]{}: {}'.format(self._rq.status_code, data.get('error_code'), data.get('error_message'))
            else:
                msg = '{}: {}'.format(self._rq.status_code, self._rq.reason)
            raise RuntimeError(msg)


class AWS(BaseTTS):
    MAX_CHARS = 3000

    # noinspection PyMissingConstructor
    def __init__(self, text, buff_size, speaker, audio_format, key, lang, *_, **__):
        if not isinstance(key, (tuple, list)) or len(key) < 3:
            raise RuntimeError('Wrong AWS key')
        params = {
            'OutputFormat': audio_format,
            'Text': text,
            'LanguageCode': lang,
            'VoiceId': speaker
        }
        self._params = {'text': text}
        self._url, self._body, self._headers = polly_signing(params, *key)
        self._buff_size = buff_size
        self._data = None
        self._rq = None

        self._request_check()
        self._request('tts_aws')
        self._reply_check()

    def _request(self, proxy_key):
        try:
            self._rq = requests.post(
                self._url,
                data=self._body,
                headers=self._headers,
                stream=True,
                timeout=30,
                proxies=proxies(proxy_key)
            )
        except REQUEST_ERRORS as e:
            raise RuntimeError(str(e))
        self._data = self._rq.iter_content


class RHVoiceREST(BaseTTS):
    def __init__(self, text, buff_size, speaker, audio_format, url, sets, *_, **__):
        super().__init__('{}/say'.format(url or 'http://127.0.0.1:8080'), 'tts_rhvoice-rest', buff_size=buff_size,
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
        self.__test = self._data.read(self._buff_size)  # Ждем запуска, иначе poll() не вернет ошибку

    def _reply_check(self):
        if self._rq.poll():
            raise RuntimeError('{}: {}'.format(self._rq.poll(), ' '.join(self._rq.stderr.read().decode().split())[:99]))

    def iter_me(self):
        if self._data is None:
            raise RuntimeError('No data')
        if self.__test:
            yield self.__test
        while True:
            chunk = self._data.read(self._buff_size)
            if not chunk:
                break
            yield chunk


def aws(key, **kwargs):
    if len(key) != 2:
        raise RuntimeError('Wrong key')
    if key[1]:
        return aws_boto3(key=key[0], **kwargs)
    else:
        return AWS(key=key[0], **kwargs)


def yandex(yandex_api, **kwargs):
    if yandex_api == 2:
        return YandexCloud(**kwargs)
    else:
        return Yandex(**kwargs)


_CALL_BY_NAME = {'google': Google, 'yandex': yandex, 'aws': aws, 'rhvoice-rest': RHVoiceREST, 'rhvoice': RHVoice}


def support(name):
    return name in _CALL_BY_NAME


def GetTTS(name, **kwargs):
    if not support(name):
        raise RuntimeError('TTS {} not found'.format(name))
    return _CALL_BY_NAME[name](**kwargs)
