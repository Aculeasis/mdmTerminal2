#!/usr/bin/env python3

import logging
import os
import queue
import threading
import time
import zlib
from logging.handlers import RotatingFileHandler

from languages import LOGGER as LNG
from owner import Owner
from utils import write_permission_check, Connect, singleton

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

LVL_NAME = {
    DEBUG: 'DEBUG',
    INFO: 'INFO ',
    WARN: 'WARN ',
    ERROR: 'ERROR',
    CRIT: 'CRIT ',
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
    REMOTE_LOG = 'remote_log'
    CHANNEL = 'net_block'

    def __init__(self, cfg: dict, owner: Owner):
        super().__init__(name='Logger')
        self._cfg = cfg
        self.own = owner
        self.file_lvl = None
        self.print_lvl = None
        self.in_print = None
        self._handler = None
        self._app_log = None
        self._conn = None
        self._conn_raw = False
        self._queue = queue.Queue()
        self._init()
        self._print('Logger', 'start', INFO)
        self.start()

    def reload(self):
        self._queue.put_nowait('reload')

    def join(self, timeout=None):
        self._print('Logger', 'stop.', INFO)
        self._queue.put_nowait(None)
        super().join()

    def run(self):
        MainLogger().connect(self.add('MAIN'))
        while True:
            data = self._queue.get()
            if isinstance(data, tuple):
                self._best_print(*data)
            elif data is None:
                break
            elif data == 'reload':
                self._init()
            elif isinstance(data, list) and len(data) == 3 and data[0] == 'remote_log':
                self._add_connect(data[1], data[2])
            else:
                self._print('Logger', 'Wrong data: {}'.format(repr(data)), ERROR)
        MainLogger().disconnect()
        self._close_connect()

    def permission_check(self):
        if not write_permission_check(self._cfg.get('file')):
            self._print('Logger', LNG['err_permission'].format(self._cfg.get('file')), CRIT)
            return False
        return True

    def _init(self):
        self.file_lvl = get_loglvl(self._cfg.get('file_lvl', 'info'))
        self.print_lvl = get_loglvl(self._cfg.get('print_lvl', 'info'))
        self.in_print = self._cfg.get('method', 3) in [2, 3] and self.print_lvl <= CRIT
        in_file = self._cfg.get('method', 3) in [1, 3] and self.file_lvl <= CRIT

        if self._cfg['remote_log']:
            # Подписка
            self.own.subscribe(self.REMOTE_LOG, self._add_remote_log, self.CHANNEL)
        else:
            # Отписка
            self.own.unsubscribe(self.REMOTE_LOG, self._add_remote_log, self.CHANNEL)
            self._close_connect()

        if self._app_log:
            self._app_log.removeHandler(self._handler)
            self._app_log = None

        if self._handler:
            self._handler.close()
            self._handler = None

        if self._cfg.get('file') and in_file and self.permission_check():
            self._handler = RotatingFileHandler(filename=self._cfg.get('file'), maxBytes=1024 * 1024,
                                                backupCount=2, delay=0
                                                )
            self._handler.rotator = _rotator
            self._handler.namer = _namer
            self._handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
            self._handler.setLevel(logging.DEBUG)

            self._app_log = logging.getLogger('logger')
            # Отключаем печать в консольку
            self._app_log.propagate = False
            self._app_log.setLevel(logging.DEBUG)
            self._app_log.addHandler(self._handler)

    def _add_remote_log(self, _, data, lock, conn: Connect):
        try:
            # Забираем сокет у сервера
            conn_ = conn.extract()
            if conn_:
                conn_.settimeout(None)
                self._queue.put_nowait(['remote_log', conn_, data == 'raw'])
        finally:
            lock()

    def _add_connect(self, conn, raw):
        self._close_connect()
        self._conn = conn
        self._conn_raw = raw
        self._print('Logger', 'OPEN REMOTE LOG FOR {}:{}'.format(self._conn.ip, self._conn.port), WARN)

    def _close_connect(self):
        if self._conn:
            try:
                self._conn.write(colored('CLOSE REMOTE LOG, BYE.', COLORS[INFO]))
                self._conn.close()
            except RuntimeError:
                pass
            finally:
                self._print('Logger', 'CLOSE REMOTE LOG FOR {}:{}'.format(self._conn.ip, self._conn.port), WARN)
            self._conn = None

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
        print_line = None
        if self.in_print and lvl >= self.print_lvl:
            print_line = self._to_print(name, msg, lvl, l_time, m_name)
            print(print_line)
        if self._conn:
            if self._conn_raw:
                print_line = self._to_print_raw(name, msg, lvl, l_time, m_name)
            elif print_line is None:
                print_line = self._to_print(name, msg, lvl, l_time, m_name)
            self._to_remote_log(print_line)
        if self._app_log and lvl >= self.file_lvl:
            if m_name:
                name = '{}->{}'.format(name, m_name)
            self._to_file(name, msg, lvl)

    def _to_file(self, name, msg, lvl):
        self._app_log.log(lvl, '{}: {}'.format(name, msg))

    def _to_print(self, name, msg, lvl, l_time, m_name) -> str:
        if m_name:
            m_name = '->{}'.format(colored(m_name, MODULE_COLOR))
        time_ = time.strftime('%Y.%m.%d %H:%M:%S', time.localtime(l_time))
        if self._cfg['print_ms']:
            time_ += '.{:03d}'.format(int(l_time * 1000 % 1000))
        return '{} {}{}: {}'.format(time_, colored(name, NAME_COLOR), m_name, colored(msg, COLORS[lvl]))

    def _to_print_raw(self, name, msg, lvl, l_time, m_name):
        if m_name:
            m_name = '->{}'.format(m_name)
        time_ = time.strftime('%Y.%m.%d %H:%M:%S', time.localtime(l_time))
        if self._cfg['print_ms']:
            time_ += '.{:03d}'.format(int(l_time * 1000 % 1000))
        return '{} {} {}{}: {}'.format(time_, LVL_NAME[lvl], name, m_name, msg)

    def _to_remote_log(self, line: str):
        if self._conn:
            try:
                self._conn.write(line)
            except RuntimeError:
                self._close_connect()


@singleton
class MainLogger:
    def __init__(self):
        self._log = self.to_print

    def to_print(self, msg , *_, **__):
        print(msg)

    def connect(self, logger):
        self._log = logger

    def disconnect(self):
        self._log = self.to_print

    def __call__(self, msg, lvl, *_, **__):
        self._log(msg, lvl)


def main_logger(msg, lvl=ERROR):
    MainLogger()(msg, lvl)
