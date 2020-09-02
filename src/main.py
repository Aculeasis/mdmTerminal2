#!/usr/bin/env python3

import os
import signal
import sys
import tempfile
from copy import deepcopy

import default_settings as _ds
from loader import Loader
from utils import SignalHandler, file_lock

HOME = os.path.abspath(sys.path[0])


def get_cfg():
    return deepcopy(_ds.CFG)


def get_state():
    return deepcopy(_ds.STATE)


def get_path(home) -> dict:
    path = {
        'home': home,
        # Временные файлы
        'tmp': tempfile.gettempdir(),
        # ~/settings.ini
        'settings': os.path.join(home, 'settings.ini'),
        # ~/.state.json
        'state': os.path.join(home, '.state.json'),
        # ~/resources/
        'resources': os.path.join(home, 'resources'),
        # ~/data/
        'data': os.path.join(home, 'data'),
        # ~/plugins/
        'plugins': os.path.join(home, 'plugins'),
        # ~/test/
        'test': os.path.join(home, 'test'),
        # Расширение тестовых файлов
        'test_ext': '.wav',
        # Бэкапы
        'backups': os.path.join(home, 'backups'),
    }
    path['models'] = os.path.join(path['resources'], 'models')
    path['samples'] = os.path.join(path['resources'], 'samples')
    # ~/resources/ding.wav ~/resources/dong.wav ~/resources/tts_error.mp3
    audio = (('ding', 'ding.wav'), ('dong', 'dong.wav'), ('bimp', 'bimp.mp3'), ('tts_error', 'tts_error.mp3'))
    for (key, val) in audio:
        path[key] = os.path.join(path['resources'], val)
    return path


def main():
    print('MAIN: Start...')
    sig = SignalHandler((signal.SIGINT, signal.SIGTERM))
    loader = Loader(init_cfg=get_cfg(), init_state=get_state(), path=get_path(HOME), sig=sig)
    try:
        loader.start_all_systems()
    except RuntimeError:
        pass
    else:
        sig.sleep(None)
    loader.stop_all_systems()
    print('MAIN: bye.')
    return loader.reload


if __name__ == '__main__':
    with file_lock(os.path.join(HOME, '.mdmterminal2.lock')):
        while main():
            pass
