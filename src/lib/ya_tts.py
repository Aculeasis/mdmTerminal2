import requests

#  Скопировано из speech_recognition для прикручивая проверки валидности ключа


class Error(Exception):
    def __init__(self, code, msg):
        self.code = code
        self.msg = msg


class TTS:
    TTS_URL = "https://tts.voicetech.yandex.net/generate"
    MAX_CHARS = 2000

    def __init__(self, text, speaker, audio_format, key, lang="ru-RU", **kwargs):
        """Class for generate of speech.

        Args:
            speaker: Speaker.
            audio_format: Audio file format.
            key: API-key for Yandex speech kit.
            lang (optional): Language. Defaults to "ru-RU".
            emotion (optional): The color of the voice. Defaults to "normal".
            speed (optional): Speech tempo. Defaults to 1.0.
        """
        self.__params = {
            "text": text,
            "speaker": speaker,
            "format": audio_format,
            "key": key,
            "lang": lang,
        }
        self.__params.update(kwargs)
        self._data = None
        self._generate()

    def _generate(self):
        """Try to get the generated file.
        """
        if not self.__params['text']:
            raise Error(code=1, msg="No text to speak")

        if len(self.__params['text']) >= self.MAX_CHARS:
            raise Error(code=2, msg="Number of characters must be less than 2000")

        try:
            rq = requests.get(self.TTS_URL, params=self.__params, stream=True)
        except (requests.exceptions.HTTPError, requests.exceptions.RequestException) as e:
            raise Error(code=1, msg=str(e))

        if rq.status_code != 200:
            msg = {400: 'Key banned or inactive', 423: 'Key locked'}
            raise Error(code=rq.status_code, msg=msg.get(rq.status_code, 'http code != 200'))
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

