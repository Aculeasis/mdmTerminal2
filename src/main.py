#!/usr/bin/env python3

import os
import signal
import sys

from server import MDTServer
from utils import SignalHandler

CFG = {  # Дефолтные настройки
    # 'apikeytts', 'apikeystt' теперь в разделах провайдеров
    'linkedroom'      : '',
    'providertts'     : 'google',
    'providerstt'     : 'google',
    'ip_server'       : '',
    'ip'              : '',
    'sensitivity'     : 0.4,
    'alarmkwactivated': 1,
    'alarmtts'        : 1,
    'alarmstt'        : 1,
    # Индекс микрофона, можно посмотреть через mic.py
    # Если -1 определит сам.
    'mic_index'   : -1,
    'mpd': {
        'control': 1,  # Будут работать play:, pause: а так же mpd будет ставится на паузу при активации. 1 или 0
        'ip': '127.0.0.1',
        'port': 6600,
        'wait': 13,  # Если автоматически поставили mpd на паузу, через сколько секунд снять
    },
    'log': {
        'file_lvl' : 'debug',  # debug info warn error crit
        'print_lvl': 'debug',
        'method': 3,  # 1 - file, 2 - print, 3 - both
        'file': '/var/log/mdmterminal.log',
    },
    'yandex': {  # эмоция и спикер доступны только для tts яндекса
        'emotion': 'good',  # good|neutral|evil
        'speaker': 'alyss',  # <jane|oksana|alyss|omazh|zahar|ermil>
        # 'apikeytts': 'key',
    },
    'rhvoice': {
        'server': 'http://127.0.0.1:8080',
        'speaker': 'anna',  # anna, aleksandr, elena, irina
    },
    'cache': {
        # Приоритет при чтении из кэша. Если не указан - текущий провайдер, иначе вначале ищет указанного.
        # * - вначале ищет текущего, потом любого.
        'tts_priority': 'yandex',
        'tts_size': 100,  # Размер tts кэша в Мб.
    },
}

# home = os.path.abspath(os.path.dirname(__file__))
home = os.path.abspath(sys.path[0])


def main():
    print('MAIN: Start...')
    sig = SignalHandler((signal.SIGINT, signal.SIGTERM))
    server = MDTServer(init_cfg=CFG.copy(), home=home, die_in=sig.die_in)
    server.start()
    while not sig.interrupted():
        sig.sleep(100)
    sig.stop()
    server.stop()
    print('MAIN: bye.')
    return server.reload


while main():
    pass






























