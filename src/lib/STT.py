
import hashlib
import json
import time
from io import BytesIO

import requests

import lib.streaming_converter as streaming_converter
from utils import REQUEST_ERRORS, RuntimeErrorTrace, url_builder_cached
from .audio_utils import StreamRecognition
from .keys_utils import requests_post, xml_yandex
from .proxy import proxies
from .sr_wrapper import google_reply_parser, UnknownValueError, Recognizer, AudioData, RequestError
from .yandex_stt_grpc import yandex_stt_grpc

__all__ = ['support', 'GetSTT', 'BaseSTT', 'RequestError']


class BaseSTT:
    BUFF_SIZE = 1024 * 4

    def __init__(self, url, audio_data: AudioData or StreamRecognition, ext,
                 headers=None, convert_rate=None, convert_width=None, proxy_key=None, **kwargs):
        self._text = None
        self._rq = None
        self._url = url
        self._headers = headers
        self._params = kwargs

        if ext in streaming_converter.CMD or isinstance(audio_data, StreamRecognition):
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
            raise RuntimeErrorTrace(e)

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

    def __init__(self, audio_data, key=None, lang='ru-RU', **_):
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

    def __init__(self, audio_data, key, lang='ru-RU', **_):
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

    def __init__(self, audio_data, key, lang='ru-RU', **_):
        ext = 'opus'
        rate = 16000
        width = 2
        headers = {'Authorization': 'Api-Key {}'.format(key)}
        kwargs = {
            'topic': 'general',
            'lang': lang,
            'profanityFilter': 'false'
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


class YandexCloudGRPC(BaseSTT):
    def __init__(self, audio_data, key, lang='ru-RU', **_):
        ext = 'pcm'
        rate = 16000
        width = 2
        self._api_key = key
        self._lang = lang
        super().__init__(None, audio_data, ext, convert_width=width, convert_rate=rate)

    def _send(self, _):
        self._text = yandex_stt_grpc(self._api_key, self._lang, self._chunks())

    def _reply_check(self):
        pass


class WitAI(BaseSTT):
    # https://wit.ai/docs/http/20170307#post__speech_link
    URL = 'https://api.wit.ai/speech'

    def __init__(self, audio_data, key, **_):
        ext = 'wav'
        rate = 16000
        width = 2
        headers = {
            'Authorization': 'Bearer {}'.format(key),
            'Content-Type': 'audio/wav'
        }
        # API version
        kwargs = {'v': '20170307'}
        super().__init__(self.URL, audio_data, ext, headers, rate, width, 'stt_wit.ai', **kwargs)

    def _parse_response(self):
        try:
            self._text = json.loads(self._rq.text)['_text']
        except (json.JSONDecodeError, ValueError) as e:
            raise RuntimeError(e)
        except KeyError as e:
            raise UnknownValueError(e)


class Azure(BaseSTT):
    # https://docs.microsoft.com/en-us/azure/cognitive-services/Speech-Service/rest-apis
    URL = 'https://{}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1'

    def __init__(self, audio_data, key, lang, **_):
        if len(key) != 2:
            raise RuntimeError('Wrong key')

        ext = 'wav'
        rate = 16000
        width = 2
        url = self.URL.format(key[1])
        headers = {
            'Authorization': 'Bearer {}'.format(key[0]),
            'Content-type': 'audio/{}; codec=audio/pcm; samplerate={}'.format(ext, rate),
            'Accept': 'application/json'
        }
        kwargs = {
            'language': lang,
            'format': 'simple',
            'profanity': 'raw',
        }
        super().__init__(url, audio_data, ext, headers, rate, width, 'stt_azure', **kwargs)

    def _parse_response(self):
        try:
            result = json.loads(self._rq.text)
            if not isinstance(result, dict):
                result = {}
        except (json.JSONDecodeError, ValueError) as e:
            raise RuntimeError(e)

        status = result.get('RecognitionStatus')
        text = result.get('DisplayText')
        if status is None:
            raise RuntimeError('Wrong reply - \'RecognitionStatus\' missing')
        if status == 'NoMatch':
            raise UnknownValueError()
        if status != 'Success':
            raise RuntimeError('Recognition error: {}'.format(status))
        if text is None:
            raise RuntimeError('Wrong reply - \'DisplayText\' missing')
        self._text = text


class PocketSphinxREST(BaseSTT):
    # https://github.com/Aculeasis/pocketsphinx-rest
    def __init__(self, audio_data: AudioData, url='', **_):
        url = url_builder_cached(url or '127.0.0.1', def_port=8085, def_path='/stt')
        super().__init__(url, audio_data, 'wav', {'Content-Type': 'audio/wav'}, 16000, 2, 'stt_pocketsphinx-rest')

    def _parse_response(self):
        try:
            result = json.loads(''.join(self._rq.text.split('\n')))
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            raise RuntimeError('Json decode error: {}'.format(e))

        if 'code' not in result or 'text' not in result or result['code']:
            raise RuntimeError('Response error: {}: {}'.format(result.get('code', 'None'), result.get('text', 'None')))
        self._text = result['text']


class Microsoft:
    def __init__(self, audio_data, key, lang, **_):
        sr = Recognizer()
        if isinstance(audio_data, StreamRecognition):
            audio_data = audio_data.get_audio_data()
        self._text = sr.recognize_bing(audio_data, key, lang)

    def text(self):
        if not self._text:
            raise UnknownValueError('No variants')
        return self._text


def yandex(yandex_api, grpc, **kwargs):
    if yandex_api == 2:
        if grpc:
            return YandexCloudGRPC(**kwargs)
        else:
            return YandexCloud(**kwargs)
    else:
        return Yandex(**kwargs)


PROVIDERS = {
    'google': Google, 'yandex': yandex, 'pocketsphinx-rest': PocketSphinxREST, 'wit.ai': WitAI, 'microsoft': Microsoft,
    'azure': Azure
}


def support(name):
    return name in PROVIDERS


def GetSTT(name, **kwargs):
    try:
        return PROVIDERS[name](**kwargs)
    except KeyError:
        raise RuntimeError('STT {} not found'.format(name))
