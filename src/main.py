#!/usr/bin/env python3

import os
import signal
import sys
import tempfile
from copy import deepcopy

from loader import Loader
from utils import SignalHandler

HOME = os.path.abspath(sys.path[0])
CFG = {  # Дефолтные настройки https://github.com/Aculeasis/mdmTerminal2/wiki/settings.ini
    'settings': {
        'providertts'     : 'google',
        'providerstt'     : 'google',
        'ip'              : '',
        'sensitivity'     : 0.4,
        'alarmkwactivated': 1,
        'alarmtts'        : 1,
        'alarmstt'        : 1,
        'first_love'      : 1,
        'last_love'       : 0,
        'mic_index'   : -1,
        'optimistic_nonblock_tts': 1,
        'ask_me_again': 0,
        'quiet': 0,
        'no_hello': 0,
        'blocking_listener': 1,
        'energy_threshold': -1,
        'phrase_time_limit': 15,
        'no_background_play': 0,
        'chrome_mode': 1,
        'chrome_choke': 0,
        'chrome_alarmstt': 0,
        'lang': 'ru',
        'lang_check': 0,
    },
    'majordomo': {
        'linkedroom': '',
        'ip': '',
        'terminal': '',
        'username': '',
        'password': '',
    },
    'mpd': {
        'control': 1,
        'ip': '127.0.0.1',
        'port': 6600,
        'wait': 13,
    },
    'log': {
        'file_lvl' : 'debug',
        'print_lvl': 'debug',
        'method': 3,
        'file': '',
    },
    'yandex': {
        'api': 1,
        'emotion': 'good',
        'speaker': 'alyss',
    },
    'aws': {
        'speaker': 'Tatyana',
        'access_key_id': '',
        'secret_access_key': '',
        'region': 'eu-central-1',
        'boto3': 0,
    },
    'rhvoice-rest': {
        'server': 'http://127.0.0.1:8080',
        'speaker': 'anna',
        'rate': 50,
        'pitch': 50,
        'volume': 50,
    },
    'rhvoice': {
        'speaker': 'anna',
    },
    'pocketsphinx-rest': {
        'server': 'http://127.0.0.1:8085',
    },
    'cache': {
        'tts_priority': 'yandex',
        'tts_size': 100,
        'path': '',
    },
    'models': {},
    'proxy': {
        'enable': 0,
        'monkey_patching': 1,
        'proxy': 'socks5h://127.0.0.1:9050'
    },
    'snowboy': {
        'clear_models': 0,
        'token': 'd4977cf8ff6ede6efb8d2277c1608c7dbebf18a7',
        'name': 'unknown',
        'age_group': '30_39',
        'gender': 'M',
        'microphone': 'mic',

    },
    'update': {
        'interval': 0,
        'pip': 1,
        'apt': 0,
        'turnoff': -1,
        'fallback': 1,
    },
    'system': {
        'ini_version': 4,
    }
}


def get_path(home) -> dict:
    path = {
        'home': home,
        # Расширение моделей
        'model_ext': '.pmdl',
        # Поддерживаемые модели
        'model_supports': ['.pmdl', '.umdl'],
        # Временные файлы
        'tmp': tempfile.gettempdir(),
    }
    # ~/settings.ini
    path['settings'] = os.path.join(path['home'], 'settings.ini')
    # ~/resources/
    path['resources'] = os.path.join(path['home'], 'resources')
    # ~/resources/models/
    path['models'] = os.path.join(path['resources'], 'models')
    # ~/resources/ding.wav ~/resources/dong.wav ~/resources/tts_error.mp3
    for (key, val) in [['ding', 'ding.wav'], ['dong', 'dong.wav'], ['tts_error', 'tts_error.mp3']]:
        path[key] = os.path.join(path['resources'], val)
    return path


def main():
    print('MAIN: Start...')
    sig = SignalHandler((signal.SIGINT, signal.SIGTERM))
    loader = Loader(init_cfg=deepcopy(CFG), path=get_path(HOME), die_in=sig.die_in)
    loader.start()
    sig.sleep(None)
    loader.stop()
    print('MAIN: bye.')
    return loader.reload


if __name__ == '__main__':
    while main():
        pass
