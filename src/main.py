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
    # Если включено и 'ip_server' не задан, то ip первого кто подключится к терминалу станет 'ip_server'.
    'first_love'      : 1,
    # Если включено, терминал будет отвергать подключения от ip не совпадающих с 'ip_server'
    # Включение этой опции без first_love сделает удаленную конфигурацию невозможной.
    'last_love'       : 0,
    # Индекс микрофона, можно посмотреть через mic.py
    # Если -1 определит сам.
    'mic_index'   : -1,
    # Если 1, то TTS не будет блокировать выполнение кода и ждать генерации аудио.
    # Это сокращает время ответа, т.к. запрос будет идти параллельно всяким динг-донгам
    # Но если время ответа слишком велико большой разрывы между сигналами и фразой будут неприятен.
    'optimistic_nonblock_tts': 0,
    'mpd': {
        # Будут работать play:, pause:. Также mpd будет ставиться на паузу при активации терминала. 1 или 0
        'control': 1,
        'ip': '127.0.0.1',
        'port': 6600,
        'wait': 13,  # Если автоматически поставили mpd на паузу, через сколько секунд снять.
    },
    'log': {
        'file_lvl' : 'debug',  # debug info warn error crit
        'print_lvl': 'debug',
        'method': 3,  # 1 - file, 2 - console, 3 - both
        'file': '/var/log/mdmterminal.log',
    },
    'yandex': {  # Эмоции есть только у tts яндекса.
        'emotion': 'good',  # good|neutral|evil
        'speaker': 'alyss',  # <jane|oksana|alyss|omazh|zahar|ermil>
        # 'apikeytts': 'key',
    },
    'rhvoice-rest': {
        # Адрес rhvoice-rest
        'server': 'http://127.0.0.1:8080',
        'speaker': 'anna',  # anna, aleksandr, elena, irina
    },
    'rhvoice': {
        # Для работы RHVoice-test и lame должны быть доступны на локальной машине
        # Проверка: echo 'This is fine' | RHVoice-test -p slt -o - | lame -th -V 4 --silent - | mpg123 -q -
        'speaker': 'anna',  # anna, aleksandr, elena, irina
    },
    'pocketsphinx-rest': {
        'server': 'http://127.0.0.1:8085',
    },
    'cache': {
        # Приоритет при поиске в кэше. Если не указан - только текущий провайдер.
        # Если указан - вначале ищет указанного потом текущего.
        # * - вначале ищет текущего, потом любого.
        'tts_priority': 'yandex',
        'tts_size': 100,  # Размер кэша в Мб. Проверка при запуске.
    },
}

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


if __name__ == '__main__':
    while main():
        pass






























