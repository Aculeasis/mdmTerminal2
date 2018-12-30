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
        'alarmkwactivated': True,
        'alarmtts'        : True,
        'alarmstt'        : True,
        'alarm_recognized': False,
        'first_love'      : True,
        'last_love'       : False,
        'mic_index'   : -1,
        'optimistic_nonblock_tts': True,
        'ask_me_again': 0,
        'quiet': False,
        'no_hello': False,
        'blocking_listener': True,
        'energy_threshold': -1,
        'audio_gain': 1.0,
        'phrase_time_limit': 15,
        'silent_multiplier': 1.0,
        'no_background_play': False,
        'chrome_mode': 1,
        'chrome_choke': False,
        'chrome_alarmstt': False,
        'webrtcvad': 0,
        'lang': 'ru',
        'lang_check': False,
    },
    'majordomo': {
        'linkedroom': '',
        'ip': '',
        'terminal': '',
        'username': '',
        'password': '',
        'object_name': '',
        'object_method': '',
        'heartbeat_timeout': 0
    },
    'mpd': {
        'control': True,
        'ip': '127.0.0.1',
        'port': 6600,
        'pause': True,
        'smoothly': False,
        'quieter': 0,
        'wait_resume': 5,
    },
    'log': {
        'file_lvl' : 'debug',
        'print_lvl': 'debug',
        'remote_log': True,
        'print_ms': True,
        'method': 3,
        'file': '',
    },
    'yandex': {
        'api': 1,
        'emotion': 'good',
        'speaker': 'alyss',
        'speed': 1.0
    },
    'google': {
        'slow': False,
    },
    'aws': {
        'speaker': 'Tatyana',
        'access_key_id': '',
        'secret_access_key': '',
        'region': 'eu-central-1',
        'boto3': False,
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
    'azure': {
        'speaker': 'EkaterinaRUS',
        'region': 'westus',
    },
    'cache': {
        'tts_priority': '',
        'tts_size': 100,
        'path': '',
    },
    'models': {
        'allow': ''
    },
    'persons': {},
    'proxy': {
        'enable': 0,
        'monkey_patching': True,
        'proxy': 'socks5h://127.0.0.1:9050'
    },
    'snowboy': {
        'clear_models': False,
        'token': 'd4977cf8ff6ede6efb8d2277c1608c7dbebf18a7',
        'name': 'unknown',
        'age_group': '30_39',
        'gender': 'M',
        'microphone': 'mic',

    },
    'update': {
        'interval': 0,
        'pip': True,
        'apt': False,
        'turnoff': -1,
        'fallback': True,
    },
    'volume': {
        'line_out': '',
    },
    'noise_suppression': {
        'enable': False,
        'conservative': False,
        'ns_lvl': 0,
    },
    'system': {
        'ini_version': 23,
        'ws_token': 'token_is_unset'
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
        # ~/settings.ini
        'settings': os.path.join(home, 'settings.ini'),
        # ~/resources/
        'resources': os.path.join(home, 'resources'),
        # ~/data/
        'data': os.path.join(home, 'data'),
    }
    path['models'] = os.path.join(path['resources'], 'models')
    # ~/resources/ding.wav ~/resources/dong.wav ~/resources/tts_error.mp3
    audio = (('ding', 'ding.wav'), ('dong', 'dong.wav'), ('bimp', 'bimp.mp3'), ('tts_error', 'tts_error.mp3'))
    for (key, val) in audio:
        path[key] = os.path.join(path['resources'], val)
    return path


def main():
    print('MAIN: Start...')
    sig = SignalHandler((signal.SIGINT, signal.SIGTERM))
    loader = Loader(init_cfg=deepcopy(CFG), path=get_path(HOME), die_in=sig.die_in)
    loader.start_all_systems()
    sig.sleep(None)
    loader.stop_all_systems()
    print('MAIN: bye.')
    return loader.reload


if __name__ == '__main__':
    while main():
        pass
