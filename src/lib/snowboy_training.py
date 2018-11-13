import base64

import requests

from utils import REQUEST_ERRORS
from .proxy import proxies


def file_to_base64(file_name) -> str:
    with open(file_name, 'rb') as fp:
        return base64.b64encode(fp.read()).decode()


class Training:
    URL = 'https://snowboy.kitt.ai/api/v1/train/'
    PARAMS = {
        'name': 'alice_mdm',
        'language': 'ru',
        'age_group': '30_39',
        'gender': 'M',
        'microphone': 'mic',  # e.g., PS3 Eye
        'token': 'd4977cf8ff6ede6efb8d2277c1608c7dbebf18a7',
    }

    def __init__(self, file1, file2, file3, params: dict or None=None):
        self.__params = self.PARAMS.copy()
        if isinstance(params, dict):
            self.__params.update(params)
        # noinspection PyTypeChecker
        self.__params['voice_samples'] = [
            {'wave': file_to_base64(file1)},
            {'wave': file_to_base64(file2)},
            {'wave': file_to_base64(file3)}
        ]
        self._data = None
        self._request()

    def _request(self):
        try:
            response = requests.post(self.URL, json=self.__params, proxies=proxies('snowboy_training'))
        except REQUEST_ERRORS as e:
            raise RuntimeError('Request error: {}'.format(e))
        if not response.ok:
            raise RuntimeError('Server error: {}'.format(response.status_code))
        self._data = response.iter_content()

    def save(self, file_path):
        if self._data is None:
            raise Exception('There\'s nothing to save')

        with open(file_path, 'wb') as fp:
            for d in self._data:
                fp.write(d)
        return file_path

