
import requests

from .stream_gTTS import gTTS as Google

__all__ = ['Google', 'Yandex', 'RhvoiceREST']


class BaseTTS:
    BUFF_SIZE = 1024

    def __init__(self, url, **kwargs):
        self._url = url
        self._params = kwargs.copy()
        self._data = None
        self._rq = None

        self._request_check()
        self._request()
        self._reply_check()

    def _request_check(self):
        if not self._params.get('text'):
            raise RuntimeError('No text to speak')

    def _request(self):
        try:
            self._rq = requests.get(self._url, params=self._params, stream=True)
        except (requests.exceptions.HTTPError, requests.exceptions.RequestException) as e:
            raise RuntimeError(str(e))
        self._data = self._rq.iter_content

    def _reply_check(self):
        if not self._rq.ok:
            raise RuntimeError('Reply error {}: {}'.format(self._rq.status_code, self._rq.reason))

    def iter_me(self):
        if self._data is None:
            raise RuntimeError('No data')
        for chunk in self._data(chunk_size=self.BUFF_SIZE):
            yield chunk

    def save_to_fp(self, fp, cb, after):
        count = 0
        for chunk in self.iter_me():
            fp.write(chunk)
            if cb is not None:
                count += 1
                if count == after:
                    cb()
                    cb = None

    def save(self, file_path, cb=None, after=0):
        with open(file_path, 'wb') as fp:
            self.save_to_fp(fp, cb, after)
        return file_path


class Yandex(BaseTTS):
    URL = 'https://tts.voicetech.yandex.net/generate'
    MAX_CHARS = 2000

    def __init__(self, text, speaker, audio_format, key, lang='ru-RU', **kwargs):
        super().__init__(self.URL, text=text, speaker=speaker, format=audio_format, key=key, lang=lang, **kwargs)

    def _request_check(self):
        super()._request_check()
        if len(self._params['text']) >= self.MAX_CHARS:
            raise RuntimeError('Number of characters must be less than 2000')

    def _reply_check(self):
        msg = {400: 'Key banned or inactive', 423: 'Key locked'}
        if self._rq.status_code in msg:
            raise RuntimeError('{}: {}'.format(self._rq.status_code, msg[self._rq.status_code]))
        super()._reply_check()


class RhvoiceREST(BaseTTS):
    def __init__(self, text, url='http://127.0.0.1:8080', voice='anna', format_='mp3'):
        super().__init__('{}/say'.format(url), text=text, format=format_, voice=voice)


