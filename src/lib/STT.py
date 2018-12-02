
import hashlib
import json
import time
from io import BytesIO

import requests
from speech_recognition import AudioData

from utils import REQUEST_ERRORS, UnknownValueError
from .proxy import proxies
from .yandex_utils import requests_post, xml_yandex, wav_to_opus

__all__ = ['Yandex', 'YandexCloud', 'PocketSphinxREST']


class BaseSTT:
    BUFF_SIZE = 1024

    def __init__(self, url, audio_data: AudioData,
                 headers=None, convert_rate=None, convert_width=None, proxy_key=None, **kwargs):
        self._text = None
        self._rq = None
        self._url = url
        self._convert_rate = convert_rate
        self._convert_width = convert_width
        self._audio = self._get_audio(audio_data)
        self._headers = {'Transfer-Encoding': 'chunked'}
        if isinstance(headers, dict):
            self._headers.update(headers)
        self._params = kwargs

        self._send(proxy_key)
        self._reply_check()
        self._parse_response()

    def _get_audio(self, audio_data: AudioData):
        return audio_data.get_wav_data(self._convert_rate, self._convert_width)

    def _chunks(self):
        with BytesIO(self._audio) as fp:
            while True:
                chunk = fp.read(self.BUFF_SIZE)
                yield chunk
                if not chunk:
                    break

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
            print(self._rq.status_code, self._rq.reason, self._rq.text)
            raise RuntimeError('{}: {}'.format(self._rq.status_code, self._rq.reason))

    def _parse_response(self):
        pass

    def text(self):
        if not self._text:
            raise UnknownValueError('No variants')
        return self._text


class Google(BaseSTT):
    URL = 'http://www.google.com/speech-api/v2/recognize'

    def __init__(self, audio_data: AudioData, key=None, lang='ru-RU'):
        rate = 16000
        width = 2
        headers = {'Content-Type': 'audio/x-flac; rate={}'.format(rate)}
        kwargs = {
            'client': 'chromium',
            'lang': lang,
            'key': key or 'AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw',
        }
        super().__init__(self.URL, audio_data, headers, rate, width, 'stt_google', **kwargs)

    def _get_audio(self, audio_data: AudioData):
        return audio_data.get_flac_data(self._convert_rate, self._convert_width)

    def _parse_response(self):
        # ignore any blank blocks
        actual_result = None
        for line in self._rq.text.split('\n'):
            if not line:
                continue
            try:
                result = json.loads(line).get('result', [])
            except json.JSONDecodeError:
                continue
            if result and isinstance(result[0], dict):
                actual_result = result[0].get('alternative')
                break

        # print(actual_result)
        if not actual_result:
            raise UnknownValueError()

        if 'confidence' in actual_result:
            # return alternative with highest confidence score
            self._text = max(actual_result, key=lambda alternative: alternative['confidence']).get('transcript')
        else:
            # when there is no confidence available, we arbitrarily choose the first hypothesis.
            self._text = actual_result[0].get('transcript')


class Yandex(BaseSTT):
    # https://tech.yandex.ru/speechkit/cloud/doc/guide/common/speechkit-common-asr-http-request-docpage/
    URL = 'https://asr.yandex.net/asr_xml'

    def __init__(self, audio_data: AudioData, key, lang='ru-RU'):
        if not key:
            raise RuntimeError('API-Key unset')
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
        super().__init__(self.URL, audio_data, headers, rate, width, 'stt_yandex', **kwargs)

    def _get_audio(self, audio_data: AudioData):
        return audio_data.get_raw_data(self._convert_rate, self._convert_width)

    def _parse_response(self):
        self._text = xml_yandex(self._rq.text)


class YandexCloud(BaseSTT):
    # https://cloud.yandex.ru/docs/speechkit/stt/request
    URL = 'https://stt.api.cloud.yandex.net/speech/v1/stt:recognize'

    def __init__(self, audio_data: AudioData, key, lang='ru-RU'):
        if not isinstance(key, (tuple, list)) or len(key) < 2:
            raise RuntimeError('Wrong Yandex APIv2 key')
        rate = 16000
        width = 2
        headers = {'Authorization': 'Bearer {}'.format(key[1])}
        kwargs = {
            'topic': 'general',
            'lang': lang,
            'profanityFilter': 'false',
            'folderId': key[0]
        }
        super().__init__(self.URL, audio_data, headers, rate, width, 'stt_yandex', **kwargs)

    def _get_audio(self, audio_data: AudioData):
        return wav_to_opus(audio_data.get_wav_data(self._convert_rate, self._convert_width))

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
    def __init__(self, audio_data: AudioData, url='http://127.0.0.1:8085'):
        url = '{}/stt'.format(url)
        super().__init__(url, audio_data, {'Content-Type': 'audio/wav'}, 16000, 2, 'stt_pocketsphinx-rest')

    def _parse_response(self):
        try:
            result = json.loads(''.join(self._rq.text.split('\n')))
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            raise RuntimeError('Json decode error: {}'.format(e))

        if 'code' not in result or 'text' not in result or result['code']:
            raise RuntimeError('Response error: {}: {}'.format(result.get('code', 'None'), result.get('text', 'None')))
        self._text = result['text']
