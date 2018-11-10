#!/usr/bin/env python3

import os
import signal
import sys
import tempfile

from loader import Loader
from utils import SignalHandler

HOME = os.path.abspath(sys.path[0])
CFG = {  # Дефолтные настройки https://github.com/Aculeasis/mdmTerminal2/wiki/settings.ini
    'linkedroom'      : '',
    'providertts'     : 'google',
    'providerstt'     : 'google',
    'ip_server'       : '',
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
    'blocking_listener': 0,
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
        'file': '/var/log/mdmterminal.log',
    },
    'yandex': {
        'emotion': 'good',
        'speaker': 'alyss',
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
    },
    'models': {},
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
    # ~/tts_cache/
    path['tts_cache'] = os.path.join(path['home'], 'tts_cache')
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
    loader = Loader(init_cfg=CFG.copy(), path=get_path(HOME), die_in=sig.die_in)
    loader.start()
    while not sig.interrupted():
        sig.sleep(100)
    sig.stop()
    loader.stop()
    print('MAIN: bye.')
    return loader.reload


if __name__ == '__main__':
    while main():
        pass






























