#!/usr/bin/env python3

import logging
import time
from logging.handlers import RotatingFileHandler

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
}


class LogWrapper:

    def __init__(self, name: str, bprint):
        self.name = name
        self._print = bprint

    def p(self, msg, lvl=DEBUG):
        self._print('{}: {}'.format(self.name, msg), lvl)


class Logger:
    COLORS = {
        logging.DEBUG:    90,
        logging.INFO:     92,
        logging.WARN:     93,
        logging.ERROR:    91,
        logging.CRITICAL: 95,
    }
    COLOR_END = '\033[0m'

    def __init__(self, cfg: dict):
        self.file_lvl = self.get_loglvl(cfg.get('file_lvl', 'info'))
        self.print_lvl = self.get_loglvl(cfg.get('print_lvl', 'info'))
        self.file = cfg.get('file', '/var/log/mdmterminal.log')
        self.in_file = cfg.get('method', 3) in [1, 3] and self.file_lvl <= CRIT
        self.in_print = cfg.get('method', 3) in [2, 3] and self.print_lvl <= CRIT

        self._app_log = None
        self._init()

    def _init(self):
        if self.file and self.in_file:
            my_handler = RotatingFileHandler(filename=self.file, maxBytes=1024 * 1024,
                                             backupCount=2, delay=0
                                             )
            my_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
            my_handler.setLevel(logging.DEBUG)

            self._app_log = logging.getLogger('logger')
            # Отключаем печать в консольку
            self._app_log.propagate = False
            self._app_log.setLevel(logging.DEBUG)
            self._app_log.addHandler(my_handler)

    def add(self, name):
        return LogWrapper(name, self.bprint).p

    @staticmethod
    def get_loglvl(str_lvl) -> int:
        return LOG_LEVEL.get(str_lvl, 100500)

    def bprint(self, msg, lvl):
        if lvl not in self.COLORS:
            raise ('Incorrect log level:{}'.format(lvl))
        if self.in_print and lvl >= self.print_lvl:
            self._to_print(msg, lvl)
        if self._app_log and lvl >= self.file_lvl:
            self._to_file(msg, lvl)

    def _to_file(self, msg, lvl):
        self._app_log.log(lvl, msg)

    def _to_print(self, msg, lvl):
        time_ = time.strftime('%Y.%m.%d %H:%M:%S', time.localtime())
        print('{} \033[{}m{}{}'.format(time_, self.COLORS[lvl], msg, self.COLOR_END))

