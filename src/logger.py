#!/usr/bin/env python3

import logging
import os
import queue
import threading
import time
import zlib
from logging.handlers import RotatingFileHandler

from utils import write_permission_check

DEBUG = logging.DEBUG
INFO = logging.INFO
WARN = logging.WARN
ERROR = logging.ERROR
CRIT = logging.CRITICAL

LOG_LEVEL = {
    'debug'   : DEBUG,
    'info'    : INFO,
    'warning' : WARN,
    'warn'    : WARN,
    'error'   : ERROR,
    'critical': CRIT,
    'crit'    : CRIT,
}

COLORS = {
    DEBUG: 90,
    INFO: 92,
    WARN: 93,
    ERROR: 91,
    CRIT: 95,
}
COLOR_END = '\033[0m'
NAME_COLOR = '1;36'
MODULE_COLOR = 36


def colored(msg, color):
    return '\033[{}m{}{}'.format(color, msg, COLOR_END)


def get_loglvl(str_lvl) -> int:
    return LOG_LEVEL.get(str_lvl, 100500)


def _namer(name):
    return name + '.gz'


def _rotator(source, dest):
    with open(source, 'rb') as sf:
        data = sf.read()
        compressed = zlib.compress(data, 9)
        with open(dest, 'wb') as df:
            df.write(compressed)
    os.remove(source)


class _LogWrapper:
    def __init__(self, name: str, print_):
        self.name = name
        self._print = print_

    def p(self, msg, lvl=DEBUG):
        self._print(self.name, msg, lvl)

    def mp(self, module_name, msg, lvl=DEBUG):
        self._print(self.name, msg, lvl, module_name)


class Logger(threading.Thread):
    def __init__(self, cfg: dict):
        super().__init__(name='Logger')
        self.file_lvl = get_loglvl(cfg.get('file_lvl', 'info'))
        self.print_lvl = get_loglvl(cfg.get('print_lvl', 'info'))
        self.file = cfg.get('file', '/var/log/mdmterminal.log')
        self.in_file = cfg.get('method', 3) in [1, 3] and self.file_lvl <= CRIT
        self.in_print = cfg.get('method', 3) in [2, 3] and self.print_lvl <= CRIT
        self._queue = queue.Queue()
        self._app_log = None
        self._init()
        self._print('Logger', 'start', INFO)
        self.start()

    def join(self, timeout=None):
        self._print('Logger', 'stop.', INFO)
        self._queue.put_nowait(None)
        super().join()

    def run(self):
        while True:
            data = self._queue.get()
            if data is None:
                break
            self._best_print(*data)

    def permission_check(self):
        if not write_permission_check(self.file):
            msg = 'Логгирование в {} невозможно - отсутствуют права на запись. Исправьте это'.format(self.file)
            self._print('Logger', msg, CRIT)
            return False
        return True

    def _init(self):
        if self.file and self.in_file and self.permission_check():
            my_handler = RotatingFileHandler(filename=self.file, maxBytes=1024 * 1024,
                                             backupCount=2, delay=0
                                             )
            my_handler.rotator = _rotator
            my_handler.namer = _namer
            my_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
            my_handler.setLevel(logging.DEBUG)

            self._app_log = logging.getLogger('logger')
            # Отключаем печать в консольку
            self._app_log.propagate = False
            self._app_log.setLevel(logging.DEBUG)
            self._app_log.addHandler(my_handler)

    def add(self, name):
        return _LogWrapper(name, self._print).p

    def add_plus(self, name):
        _ = _LogWrapper(name, self._print)
        return _.p, _.mp

    def _print(self, *args):
        self._queue.put_nowait((time.time(), *args))

    def _best_print(self, l_time, name, msg, lvl, m_name=''):
        if lvl not in COLORS:
            raise RuntimeError('Incorrect log level:{}'.format(lvl))
        if self.in_print and lvl >= self.print_lvl:
            self._to_print(name, msg, lvl, l_time, m_name)
        if self._app_log and lvl >= self.file_lvl:
            if m_name:
                name = '{}->{}'.format(name, m_name)
            self._to_file(name, msg, lvl)

    def _to_file(self, name, msg, lvl):
        self._app_log.log(lvl, '{}: {}'.format(name, msg))

    @staticmethod
    def _to_print(name, msg, lvl, l_time, m_name):
        if m_name:
            m_name = '->{}'.format(colored(m_name, MODULE_COLOR))
        time_ = time.strftime('%Y.%m.%d %H:%M:%S', time.localtime(l_time))
        print('{} {}{}: {}'.format(time_, colored(name, NAME_COLOR), m_name, colored(msg, COLORS[lvl])))

