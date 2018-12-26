import json
from collections import OrderedDict

import requests

from utils import REQUEST_ERRORS, RuntimeErrorTrace, file_to_base64
from .proxy import proxies


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
            raise RuntimeErrorTrace(e)
        if not response.ok:
            raise RuntimeError(
                'Server error {}: {} ({})'.format(
                    response.status_code,
                    response.reason,
                    pretty_errors(response.text))
            )
        self._data = response.iter_content()

    def save(self, file_path):
        if self._data is None:
            raise Exception('There\'s nothing to save')

        with open(file_path, 'wb') as fp:
            for d in self._data:
                fp.write(d)
        return file_path


def pretty_errors(text):
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError()
    except (TypeError, json.JSONDecodeError, ValueError):
        return text
    # parse `{"detail":"Authentication credentials were not provided."}`
    if data.get('detail'):
        return data['detail']
    # parse `{"voice_samples":[{},{"wave":["Hotword is too long"]},{}]}`
    if isinstance(data.get('voice_samples', ''), list) and len(data['voice_samples']) == 3:
        err = OrderedDict()
        for idx in range(3):
            if isinstance(data['voice_samples'][idx], dict) and data['voice_samples'][idx].get('wave'):
                reasons = data['voice_samples'][idx].get('wave')
                if isinstance(reasons, str):
                    reasons = [reasons]
                elif not isinstance(reasons, list):
                    continue
                for msg in reasons:
                    err[msg] = err.get(msg, [])
                    ids = str(idx+1)
                    if ids not in err[msg]:
                        err[msg].append(ids)
        if err:
            text = ';'.join(['{} for samples: {}'.format(repr(msg), ', '.join(err[msg])) for msg in err])
    return text
