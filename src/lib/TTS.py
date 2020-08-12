
import hashlib
import subprocess
import time
from functools import lru_cache
from shlex import quote

import requests

from utils import (
    REQUEST_ERRORS, RuntimeErrorTrace, yandex_speed_normalization, url_builder_cached, yandex_cloud_reply_check
)
from .gtts_monkey_patching import Google, gTTSError
from .keys_utils import YandexSessionStorage
from .polly_boto3 import AWSBoto3
from .polly_signing import signing as polly_signing
from .proxy import proxies

__all__ = ['support', 'GetTTS', 'BaseTTS', 'gTTSError']


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
            raise RuntimeErrorTrace(e)
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
            raise RuntimeErrorTrace(e)

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

    def __init__(self, text, buff_size, speaker, key, emotion, lang, speed, *_, **__):
        speed = yandex_speed_normalization(speed)
        super().__init__(self.URL, 'tts_yandex', buff_size=buff_size, text=text, speaker=speaker,
                         format='mp3', key=key, lang=lang, emotion=emotion, speed=speed)


class YandexCloud(BaseTTS):
    # https://cloud.yandex.ru/docs/speechkit/tts/request
    URL = 'https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize'
    MAX_CHARS = 5000

    def __init__(self, text, buff_size, speaker, key, emotion, lang, speed, *_, **__):
        speed = yandex_speed_normalization(speed)
        self._headers = {'Authorization': 'Api-Key {}'.format(key)}
        super().__init__(self.URL, 'tts_yandex', buff_size=buff_size, text=text, voice=speaker,
                         format='oggopus', lang=lang, emotion=emotion, speed=speed)

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
            raise RuntimeErrorTrace(e)
        self._data = self._rq.iter_content

    def _reply_check(self):
        yandex_cloud_reply_check(self._rq)


class YandexCloudDemo(BaseTTS):
    URL = 'https://cloud.yandex.ru/api/speechkit/tts'
    MAX_CHARS = 5000

    def __init__(self, text, buff_size, speaker, emotion, lang, speed, *_, **__):
        self.session = YandexSessionStorage()
        super().__init__(self.URL, 'tts_yandex', buff_size=buff_size, text=text, voice=speaker,
                         format='oggopus', lang=lang, emotion=emotion, speed=yandex_speed_normalization(speed))

    def _request(self, proxy_key):
        self.session.update()

        self._params['message'] = self._params.pop('text')
        try:
            self._rq = requests.post(
                self._url,
                json=self._params,
                cookies=self.session.cookies,
                headers=self.session.headers,
                stream=True,
                timeout=30,
                proxies=proxies(proxy_key)
            )
        except REQUEST_ERRORS as e:
            raise RuntimeErrorTrace(e)
        self._data = self._rq.iter_content

    def _reply_check(self):
        yandex_cloud_reply_check(self._rq)
        # noinspection PyBroadException
        try:
            self.session.update(self._rq)
        except Exception:
            pass


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
            raise RuntimeErrorTrace(e)
        self._data = self._rq.iter_content


class Azure(AWS):
    # https://docs.microsoft.com/en-us/azure/cognitive-services/Speech-Service/rest-apis
    URL = 'https://{}.tts.speech.microsoft.com/cognitiveservices/v1'
    MAX_CHARS = 1000

    # noinspection PyMissingConstructor
    def __init__(self, text, buff_size, speaker, key, lang, *_, **__):
        if len(key) != 2:
            raise RuntimeError('Wrong key')

        self._data = None
        self._rq = None
        self._body = [
            "<speak version='1.0' xml:lang='{lang}'><voice xml:lang='{lang}'"
            "    name='Microsoft Server Speech Text to Speech Voice ({lang}, {speaker})'>",
            "        {text}",
            "</voice></speak>"
        ]
        self._body = '\n'.join(self._body).format(lang=lang, speaker=speaker, text=text).encode()
        self._headers = {
            'X-Microsoft-OutputFormat': 'audio-24khz-160kbitrate-mono-mp3',
            'Content-Type': 'application/ssml+xml',
            'Authorization': 'Bearer {}'.format(key[0]),
            'User-Agent': hashlib.sha1(str(time.time()).encode()).hexdigest()[:32]
        }
        self._url = self.URL.format(key[1])
        self._buff_size = buff_size

        if len(self._body) >= self.MAX_CHARS:
            raise RuntimeError('Number of characters must be less than {}'.format(self.MAX_CHARS))

        self._request('tts_azure')
        self._reply_check()


class RHVoiceREST(BaseTTS):
    def __init__(self, text, buff_size, speaker, audio_format, url, sets, *_, **__):
        url = url_builder_cached(url or '127.0.0.1', def_port=8080, def_path='/say')
        super().__init__(url, 'tts_rhvoice-rest', buff_size=buff_size,
                         text=text, format=audio_format, voice=speaker or 'anna', **sets)


class RHVoiceWrapper:
    def __init__(self, text, speaker, audio_format, sets, *_, **__):
        if not text:
            raise RuntimeError('No text to speak')
        self._generator = _rhvoice_wrapper().gen(text, speaker, audio_format, sets)
        # dirty hack for accurate time calculation
        next(self._generator)

    def stream_to_fps(self, fps):
        if not isinstance(fps, list):
            fps = [fps]
        for chunk in self._generator:
            for f in fps:
                f.write(chunk)

    def save(self, file_path):
        with open(file_path, 'wb') as fp:
            self.stream_to_fps(fp)
        return file_path


@lru_cache(maxsize=1)
def _rhvoice_wrapper():
    from rhvoice_wrapper import TTS as _TTS

    class TTS(_TTS):
        def gen(self, text, voice, format_, sets):
            with self.say(text, voice or 'anna', format_, None, _prepare_sets(sets) if sets else None) as read:
                yield None
                yield from read
    return TTS(threads=1, force_process=False, quiet=True)


def _prepare_sets(sets: dict) -> dict:
    def normalize_set(val):  # 0..100 -> -1.0..1
        try:
            return max(0, min(100, val)) / 50.0 - 1
        except (TypeError, ValueError):
            return 0.0
    keys = {'rate': 'absolute_rate', 'pitch': 'absolute_pitch', 'volume': 'absolute_volume'}
    return {keys[set_]: normalize_set(sets[set_]) for set_ in sets if set_ in keys}


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
            prepare_err = [line for line in self._rq.stderr.read().decode().split('\n') if not line.startswith('ALSA')]
            raise RuntimeError('{}: {}'.format(self._rq.poll(), ' '.join(prepare_err)[:99]))

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
    return AWSBoto3(key=key[0], **kwargs) if key[1] else AWS(key=key[0], **kwargs)


def yandex(yandex_api, **kwargs):
    if yandex_api == 2:
        return YandexCloud(**kwargs)
    elif yandex_api == 3:
        return YandexCloudDemo(**kwargs)
    else:
        return Yandex(**kwargs)


def rhvoice_rest(**kwargs):
    return RHVoiceREST(**kwargs) if kwargs['url'] else RHVoiceWrapper(**kwargs)


PROVIDERS = {
    'google': Google, 'yandex': yandex, 'aws': aws, 'azure': Azure, 'rhvoice-rest': rhvoice_rest, 'rhvoice': RHVoice
}


def support(name):
    return name in PROVIDERS


def GetTTS(name, **kwargs):
    try:
        tts = PROVIDERS[name]
    except KeyError:
        raise RuntimeError('TTS {} not found'.format(name))
    return tts(**kwargs)
