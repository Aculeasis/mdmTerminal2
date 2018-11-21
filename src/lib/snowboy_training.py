import base64

import requests

from utils import REQUEST_ERRORS
from .proxy import proxies


def file_to_base64(file_name: str) -> str:
    with open(file_name, 'rb') as fp:
        return base64.b64encode(fp.read()).decode()


class Training:
    # API http://docs.kitt.ai/snowboy/#api-v1-train
    URL = 'https://snowboy.kitt.ai/api/v1/train/'

    PARAMS1 = {
        'name': 'unknown',
        'microphone': 'mic'
    }
    PARAMS2 = {
        'language': (
            {'ar', 'zh', 'nl', 'en', 'fr', 'dt', 'hi', 'it', 'jp', 'ko', 'fa', 'pl', 'pt', 'ru', 'es', 'ot'}, 'ru'
        ),
        'age_group': ({'0_9', '10_19', '20_29', '30_39', '40_49', '50_59', '60+'}, '30_39'),
        'gender': ({'F', 'M'}, 'M'),
    }

    def __init__(self, file1: str, file2: str, file3: str, params: dict or None=None):
        self.__params = params if isinstance(params, dict) else {}
        self._check_params()
        self.__params['voice_samples'] = [
            {'wave': file_to_base64(file1)},
            {'wave': file_to_base64(file2)},
            {'wave': file_to_base64(file3)}
        ]
        self._data = None
        self._request()

    def _check_params(self):
        for key in self.PARAMS1:
            self.__params[key] = self.__params.get(key) or self.PARAMS1[key]
        for key in self.PARAMS2:
            if self.__params.get(key) not in self.PARAMS2[key][0]:
                self.__params[key] = self.PARAMS2[key][1]

    def _request(self):
        try:
            response = requests.post(self.URL, json=self.__params, proxies=proxies('snowboy_training'))
        except REQUEST_ERRORS as e:
            raise RuntimeError('Request error: {}'.format(e))
        if not response.ok:
            raise RuntimeError('Server error {}: {} ({})'.format(response.status_code, response.reason, response.text))
        self._data = response.iter_content()

    def save(self, file_path):
        if self._data is None:
            raise Exception('There\'s nothing to save')

        with open(file_path, 'wb') as fp:
            for d in self._data:
                fp.write(d)
        return file_path

