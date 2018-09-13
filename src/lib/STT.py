
import hashlib
import json
import time
from io import BytesIO

import requests
from bs4 import BeautifulSoup
from speech_recognition import AudioData

__all__ = ['Yandex', 'PocketSphinxREST']


class BaseSTT:
    BUFF_SIZE = 1024

    def __init__(self, url, audio_data: AudioData, headers=None, convert_rate=None, convert_width=None, **kwargs):
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

        self._send()
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

    def _send(self):
        try:
            self._rq = requests.post(
                self._url,
                data=self._chunks(),
                params=self._params,
                headers=self._headers,
                stream=True
            )
        except (requests.exceptions.HTTPError, requests.exceptions.RequestException) as e:
            raise RuntimeError(str(e))

    def _reply_check(self):
        if not self._rq.ok:
            msg = BeautifulSoup(self._rq.text, features='html.parser').text.replace('\n', ' ')[:99]
            raise RuntimeError('{}: {}'.format(self._rq.status_code, msg))

    def _parse_response(self):
        pass

    def text(self):
        return self._text


class Yandex(BaseSTT):
    URL = 'https://asr.yandex.net/asr_xml'

    def __init__(self, audio_data: AudioData, key, lang='ru-RU'):
        # https://tech.yandex.ru/speechkit/cloud/doc/guide/common/speechkit-common-asr-http-request-docpage/
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
        super().__init__(self.URL, audio_data, headers, rate, width, **kwargs)

    def _get_audio(self, audio_data: AudioData):
        return audio_data.get_raw_data(self._convert_rate, self._convert_width)

    def _parse_response(self):
        # https://tech.yandex.ru/speechkit/cloud/doc/guide/common/speechkit-common-asr-http-response-docpage/
        text = ''
        for test in self._rq.text.split('\n'):
            if test.startswith('\t'):
                text = test[1:]
        end_point = 10  # '</variant>'
        if len(text) > end_point + 2:
            text = text[:-end_point]
            try:
                start_point = text.index('>') + 1  # .....>
            except ValueError:
                text = ''
            else:
                text = text[start_point:]
        else:
            text = ''
        if not text:
            raise RuntimeError('Parse error')
        self._text = text


class PocketSphinxREST(BaseSTT):
    def __init__(self, audio_data: AudioData, url='http://127.0.0.1:8085'):
        super().__init__('{}/stt'.format(url), audio_data, {'Content-Type': 'audio/wav'}, 16000, 2)

    def _parse_response(self):
        try:
            result = json.loads(''.join(self._rq.text.split('\n')))
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            raise RuntimeError('Json decode error: {}'.format(e))

        if 'code' not in result or 'text' not in result or result['code']:
            raise RuntimeError('Response error: {}: {}'.format(result.get('code', 'None'), result.get('text', 'None')))
        self._text = result['text']
