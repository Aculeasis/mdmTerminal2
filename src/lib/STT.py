
import hashlib
import json
import threading
import time
from io import BytesIO

import requests
from websocket import create_connection, ABNF

import lib.streaming_converter as streaming_converter
from lib.yandex.stt_grpc import yandex_stt_grpc
from utils import REQUEST_ERRORS, RuntimeErrorTrace, url_builder_cached
from .audio_utils import StreamRecognition
from .keys_utils import requests_post, xml_yandex
from .proxy import proxies
from .sr_wrapper import google_reply_parser, UnknownValueError, Recognizer, AudioData, RequestError

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

    @staticmethod
    def _requests_kwargs() -> dict:
        return {}

    def _send(self, proxy_key):
        try:
            self._rq = requests.post(
                self._url,
                data=self._chunks(),
                params=self._params,
                headers=self._headers,
                stream=True,
                timeout=60,
                proxies=proxies(proxy_key),
                **self._requests_kwargs()
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

    @staticmethod
    def _requests_kwargs():
        # ssl.CertificateError: hostname 'asr.yandex.net' doesn't match 'tts.voicetech.yandex.net'
        return {'verify': False}

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


class YandexCloudDemo(BaseSTT, threading.Thread):
    URL = 'wss://cloud.yandex.ru/api/speechkit/recognition'
    ORIGIN = 'https://cloud.yandex.ru'

    def __init__(self, audio_data, lang='ru-RU', **_):
        threading.Thread.__init__(self)
        ext, rate, width = 'pcm', 16000, 2
        self.work, self._ws, self._data = False, None, None
        BaseSTT.__init__(
            self, self.URL, audio_data, ext, convert_rate=rate, convert_width=width,
            proxy_key='stt_yandex', language=lang, format=ext, sampleRate=rate,
        )

    def _send(self, proxy_key):
        try:
            self._ws = create_connection(
                self.URL,
                timeout=20,
                origin=self.ORIGIN,
                **proxies(proxy_key, ws_format=True),
            )
            self._ws.send(json.dumps(self._params))
            self._ws.recv()  # wait {'type': 'connect', 'data': 'Done'}
            self.start()
            for chunk in self._chunks():
                if not self.work:
                    break
                self._ws.send_binary(chunk)
            self.join()
        except Exception as e:
            self.close()
            raise RuntimeErrorTrace(e)

    def _reply_check(self):
        if isinstance(self._data, dict):
            try:
                self._text = self._data['chunks'][0]['alternatives'][0]['text']
            except (KeyError, TypeError, IndexError):
                pass

    def close(self):
        # noinspection PyBroadException
        try:
            self._ws.close()
        except Exception:
            pass

    def start(self):
        self.work = True
        super().start()

    def join(self, timeout=3):
        self.work = False
        self.close()
        super().join(timeout)

    def run(self):
        while self.work:
            # noinspection PyBroadException
            try:
                data = json.loads(self._ws.recv())
            except (json.JSONDecodeError, TypeError, BlockingIOError):
                continue
            except Exception:
                break
            if isinstance(data, dict) and 'type' in data:
                if data['type'] == 'data':
                    if 'data' in data and data['data']:
                        self._data = data['data']
                elif data['type'] in ('end', 'error'):
                    break
        self.work = False


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


class VoskServer(BaseSTT):
    # https://alphacephei.com/vosk/server
    # https://github.com/alphacep/vosk-server/blob/master/websocket/asr_server.py
    def __init__(self, audio_data: AudioData, url='', **_):
        self.rate = audio_data.sample_rate if audio_data.sample_rate < 16000 else 16000
        url = url_builder_cached(url or '127.0.0.1', def_port=2700)
        super().__init__(url, audio_data, 'wav', convert_rate=self.rate, convert_width=2, proxy_key='stt_vosk-rest')

    def _send(self, proxy_key):
        try:
            self._rq = create_connection(
                self._url,
                timeout=60,
                **proxies(proxy_key, ws_format=True),
            )
            self._rq.send(json.dumps({'config': {'sample_rate': self.rate}}))
            for chunk in self._chunks():
                self._rq.send(chunk, opcode=ABNF.OPCODE_BINARY)
            self._rq.send('{"eof" : 1}')
        except REQUEST_ERRORS as e:
            self._close()
            raise RuntimeErrorTrace(e)

    def _reply_check(self):
        try:
            while True:
                recv = json.loads(self._rq.recv())
                if 'partial' in recv:
                    self._text = recv['partial']
                elif 'text' in recv:
                    self._text = recv['text']
                    break
        except REQUEST_ERRORS as e:
            if not self._text:
                raise RuntimeError(e)
        finally:
            self._close()

    def _close(self):
        if self._rq:
            # noinspection PyBroadException
            try:
                self._rq.close()
            except Exception:
                pass


class BaseMySTT(BaseSTT):
    def _parse_response(self):
        try:
            result = json.loads(''.join(self._rq.text.split('\n')))
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            raise RuntimeError('Json decode error: {}'.format(e))

        if 'code' not in result or 'text' not in result or result['code']:
            raise RuntimeError('Response error: {}: {}'.format(result.get('code', 'None'), result.get('text', 'None')))
        self._text = result['text']


class PocketSphinxREST(BaseMySTT):
    # https://github.com/Aculeasis/pocketsphinx-rest
    def __init__(self, audio_data: AudioData, url='', **_):
        url = url_builder_cached(url or '127.0.0.1', def_port=8085, def_path='/stt')
        super().__init__(url, audio_data, 'wav', {'Content-Type': 'audio/wav'}, 16000, 2, 'stt_pocketsphinx-rest')


class VoskREST(BaseMySTT):
    # https://github.com/Aculeasis/vosk-rest
    def __init__(self, audio_data: AudioData, url='', **_):
        url = url_builder_cached(url or '127.0.0.1', def_port=8086, def_path='/stt')
        super().__init__(url, audio_data, 'wav', {'Content-Type': 'audio/wav'}, 16000, 2, 'stt_vosk-rest')


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
    elif yandex_api == 3:
        return YandexCloudDemo(**kwargs)
    else:
        return Yandex(**kwargs)


def vosk_rest(url: str, **kwargs):
    class_ = VoskServer if url.startswith('ws://') else VoskREST
    return class_(url=url, **kwargs)


PROVIDERS = {
    'google': Google, 'yandex': yandex, 'pocketsphinx-rest': PocketSphinxREST, 'vosk-rest': vosk_rest, 'wit.ai': WitAI,
    'microsoft': Microsoft, 'azure': Azure
}


def support(name):
    return name in PROVIDERS


def GetSTT(name, **kwargs):
    try:
        stt = PROVIDERS[name]
    except KeyError:
        raise RuntimeError('STT {} not found'.format(name))
    return stt(**kwargs)
