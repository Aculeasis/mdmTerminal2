
import hashlib
import json
import time
from io import BytesIO

import requests

import lib.streaming_converter as streaming_converter
from utils import REQUEST_ERRORS
from .proxy import proxies
from .sr_wrapper import google_reply_parser, UnknownValueError, Recognizer, AudioData, StreamRecognition, RequestError
from .yandex_utils import requests_post, xml_yandex

__all__ = ['support', 'GetSTT', 'RequestError']


class BaseSTT:
    BUFF_SIZE = 1024 * 4

    def __init__(self, url, audio_data: AudioData, ext,
                 headers=None, convert_rate=None, convert_width=None, proxy_key=None, **kwargs):
        self._text = None
        self._rq = None
        self._url = url
        self._headers = headers
        self._params = kwargs

        if ext in streaming_converter.CMD or not isinstance(audio_data, AudioData):
            self._data = streaming_converter.AudioConverter(audio_data, ext, convert_rate, convert_width)
        elif ext == 'wav':
            self._data = BytesIO(audio_data.get_wav_data(convert_rate, convert_width))
        elif ext == 'pcm':
            self._data = BytesIO(audio_data.get_raw_data(convert_rate, convert_width))
        else:
            raise RuntimeError('Unknown format: {}'.format(ext))

        self._send(proxy_key)
        self._reply_check()
        self._parse_response()

    def _chunks(self):
        chunk = True
        with self._data as fp:
            while chunk:
                chunk = fp.read(self.BUFF_SIZE)
                yield chunk

    def _send(self, proxy_key):
        try:
            self._rq = requests.post(
                self._url,
                data=self._chunks(),
                params=self._params,
                headers=self._headers,
                stream=True,
                timeout=60,
                proxies=proxies(proxy_key)
            )
        except REQUEST_ERRORS as e:
            raise RuntimeError(str(e))

    def _reply_check(self):
        if not self._rq.ok:
            raise RuntimeError('{}: {}'.format(self._rq.status_code, self._rq.reason))

    def _parse_response(self):
        pass

    def text(self):
        if not self._text:
            raise UnknownValueError('No variants')
        return self._text


class Google(BaseSTT):
    URL = 'http://www.google.com/speech-api/v2/recognize'

    def __init__(self, audio_data: AudioData, key=None, lang='ru-RU', **_):
        ext = 'flac'
        rate = 16000
        width = 2
        headers = {'Content-Type': 'audio/x-flac; rate={}'.format(rate)}
        kwargs = {
            'client': 'chromium',
            'lang': lang,
            'key': key or 'AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw',
        }
        super().__init__(self.URL, audio_data, ext, headers, rate, width, 'stt_google', **kwargs)

    def _parse_response(self):
        self._text = google_reply_parser(self._rq.text)


class Yandex(BaseSTT):
    # https://tech.yandex.ru/speechkit/cloud/doc/guide/common/speechkit-common-asr-http-request-docpage/
    URL = 'https://asr.yandex.net/asr_xml'

    def __init__(self, audio_data: AudioData, key, lang='ru-RU', **_):
        if not key:
            raise RuntimeError('API-Key unset')
        ext = 'pcm'
        rate = 16000
        width = 2
        headers = {'Content-Type': 'audio/x-pcm;bit={};rate={}'.format(width*8, rate)}
        kwargs = {
            'uuid': hashlib.sha1(str(time.time()).encode()).hexdigest()[:32],
            'key': key,
            'topic': 'queries',
            'lang': lang,
            'disableAntimat': 'true'
        }
        super().__init__(self.URL, audio_data, ext, headers, rate, width, 'stt_yandex', **kwargs)

    def _parse_response(self):
        self._text = xml_yandex(self._rq.text)


class YandexCloud(BaseSTT):
    # https://cloud.yandex.ru/docs/speechkit/stt/request
    URL = 'https://stt.api.cloud.yandex.net/speech/v1/stt:recognize'

    def __init__(self, audio_data: AudioData, key, lang='ru-RU', **_):
        if not isinstance(key, (tuple, list)) or len(key) < 2:
            raise RuntimeError('Wrong Yandex APIv2 key')
        ext = 'opus'
        rate = 16000
        width = 2
        headers = {'Authorization': 'Bearer {}'.format(key[1])}
        kwargs = {
            'topic': 'general',
            'lang': lang,
            'profanityFilter': 'false',
            'folderId': key[0]
        }
        super().__init__(self.URL, audio_data, ext, headers, rate, width, 'stt_yandex', **kwargs)

    def _send(self, proxy_key):
        self._text = requests_post(
            self._url,
            'result',
            data=self._chunks(),
            params=self._params,
            headers=self._headers,
            stream=True,
            timeout=60,
            proxies=proxies(proxy_key)
        )

    def _reply_check(self):
        pass


class PocketSphinxREST(BaseSTT):
    # https://github.com/Aculeasis/pocketsphinx-rest
    def __init__(self, audio_data: AudioData, url='http://127.0.0.1:8085', **_):
        url = '{}/stt'.format(url)
        super().__init__(url, audio_data, 'wav', {'Content-Type': 'audio/wav'}, 16000, 2, 'stt_pocketsphinx-rest')

    def _parse_response(self):
        try:
            result = json.loads(''.join(self._rq.text.split('\n')))
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            raise RuntimeError('Json decode error: {}'.format(e))

        if 'code' not in result or 'text' not in result or result['code']:
            raise RuntimeError('Response error: {}: {}'.format(result.get('code', 'None'), result.get('text', 'None')))
        self._text = result['text']


def wit_ai(audio_data, key, **_):
    sr = Recognizer()
    if isinstance(audio_data, StreamRecognition):
        audio_data = audio_data.get_audio_data()
    return sr.recognize_wit(audio_data, key)


def microsoft(audio_data, key, lang, **_):
    sr = Recognizer()
    if isinstance(audio_data, StreamRecognition):
        audio_data = audio_data.get_audio_data()
    return sr.recognize_bing(audio_data, key, lang)


def yandex(yandex_api, **kwargs):
    if yandex_api == 2:
        return YandexCloud(**kwargs)
    else:
        return Yandex(**kwargs)


PROVIDERS = {
    'google': Google, 'yandex': yandex, 'pocketsphinx-rest': PocketSphinxREST, 'wit.ai': wit_ai, 'microsoft': microsoft
}


def support(name):
    return name in PROVIDERS


def GetSTT(name, **kwargs):
    if not support(name):
        raise RuntimeError('STT {} not found'.format(name))
    if name in {'wit.ai', 'microsoft'}:
        return PROVIDERS[name](**kwargs)
    else:
        return PROVIDERS[name](**kwargs).text()
