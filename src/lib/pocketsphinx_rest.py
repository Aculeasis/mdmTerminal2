#!/usr/bin/env python3

from speech_recognition import AudioData  # pip3 install SpeechRecognition
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import json


class STT:
    def __init__(self, audio_data: AudioData, url='http://127.0.0.1:8085'):
        self._text = None
        wav_data = audio_data.get_wav_data(convert_rate=16000, convert_width=2)
        request = Request('{}/stt'.format(url), data=wav_data, headers={'Content-Type': 'audio/wav'})
        try:
            response = urlopen(request)
        except HTTPError as e:
            raise RuntimeError('Request failed: {}'.format(e.reason))
        except URLError as e:
            raise RuntimeError('Connection failed: {}'.format(e.reason))
        response_text = response.read().decode('utf-8')
        try:
            result = json.loads(response_text)
        except (json.JSONDecodeError, ValueError) as e:
            raise RuntimeError('Json decode error: {}'.format(e))

        if 'code' not in result or 'text' not in result or result['code']:
            raise RuntimeError('Server error: {}: {}'.format(result.get('code', 'None'), result.get('text', 'None')))
        self._text = result['text']

    def text(self):
        return self._text
