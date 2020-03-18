#!/usr/bin/env python3

import logging
import os
import queue
import threading
import time
import zlib
from logging.handlers import RotatingFileHandler
from functools import lru_cache
import json

from languages import F
from owner import Owner
from utils import write_permission_check
from uuid import uuid4

DEBUG = logging.DEBUG
INFO = logging.INFO
WARN = logging.WARN
ERROR = logging.ERROR
CRIT = logging.CRITICAL
# Спецсообщения для удаленного логгера
_REMOTE = 999

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
    _REMOTE: 'REMOTE',
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

REMOTE_LOG_MODE = {'raw', 'json', 'colored'}
REMOTE_LOG_DEFAULT = 'colored'


def _to_print_json(l_time: float, names: tuple, msg: str, lvl: int) -> str:
    return json.dumps({'lvl': LVL_NAME[lvl], 'time': l_time, 'callers': names, 'msg': msg}, ensure_ascii=False)


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


@lru_cache(maxsize=512)
def _name_builder(names: tuple, colored_=False):
    result = []
    for num, name in enumerate(names):
        result.append(colored(name, NAME_COLOR if not num else MODULE_COLOR) if colored_ else name)
    return '->'.join(result)


class _LogWrapper:
    def __init__(self, name: str or tuple, call_event):
        self.name = (name,) if isinstance(name, str) else name
        self._call_event = call_event

    def _print(self, *args):
        self._call_event(time.time(), *args)

    def __call__(self, msg: str, lvl=DEBUG):
        self._print(self.name, msg, lvl)

    def module(self, module_name: str, msg: str, lvl=DEBUG):
        self._print(self.name + (module_name,), msg, lvl)

    def add(self, name: str):
        return _LogWrapper(self.name + (name,), self._call_event)


class Logger(threading.Thread):
    EVENT = 'log'

    def __init__(self, tmp_own: Owner):
        super().__init__(name='Logger')
        self._queue = queue.Queue()
        self._call_event = tmp_own.registration(self.EVENT)
        tmp_own.subscribe(self.EVENT, self._event)
        self.cfg, self.own = None, None
        self.file_lvl = None
        self.print_lvl = None
        self.in_print = None
        self._handler = None
        self._app_log = None
        self._await = None
        self.remote_log = None
        self.log = self.add('Logger')
        self.log('start', INFO)

    def _event(self, _, *args, **__):
        self._queue.put_nowait(args)

    def init(self, cfg, owner: Owner):
        self.cfg = cfg['log']
        self.own = owner
        self.remote_log = RemoteLogger(cfg, owner, self.log.add('Remote'))
        self.remote_log.init()
        self._init()
        self.start()

    def reload(self):
        self.remote_log.reload()
        self._queue.put_nowait('reload')

    def join(self, timeout=30):
        self.log('stop', INFO)
        self._await = '{}'.format(uuid4())
        self.log(self._await)
        super().join(timeout=timeout)
        self.own.unsubscribe(self.EVENT, self._event)

    def run(self):
        while True:
            data = self._queue.get()
            if isinstance(data, tuple):
                if self._await and self._await == data[2]:
                    break
                self._best_print(*data)
            elif data is None:
                break
            elif data == 'reload':
                self._init()
            else:
                self.log('Wrong data: {}'.format(repr(data)), ERROR)
        self._stop_file_logging()

    def permission_check(self):
        if not write_permission_check(self.cfg.get('file')):
            msg = 'Логгирование в {} невозможно - отсутствуют права на запись. Исправьте это'
            self.log(F(msg, self.cfg.get('file')), CRIT)
            return False
        return True

    def _stop_file_logging(self):
        if self._app_log:
            self._app_log.removeHandler(self._handler)
            self._app_log = None
        if self._handler:
            self._handler.close()
            self._handler = None

    def _init(self):
        self.file_lvl = get_loglvl(self.cfg.get('file_lvl', 'info'))
        self.print_lvl = get_loglvl(self.cfg.get('print_lvl', 'info'))
        self.in_print = self.cfg.get('method', 3) in [2, 3] and self.print_lvl <= CRIT
        in_file = self.cfg.get('method', 3) in [1, 3] and self.file_lvl <= CRIT

        self._stop_file_logging()

        if self.cfg.get('file') and in_file and self.permission_check():
            self._handler = RotatingFileHandler(filename=self.cfg.get('file'), maxBytes=1024 * 1024,
                                                backupCount=2, encoding='utf8',
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

    def add(self, name) -> _LogWrapper:
        return _LogWrapper(name, self._call_event)

    def _best_print(self, l_time: float, names: tuple, msg: str, lvl: int):
        if lvl not in COLORS:
            raise RuntimeError('Incorrect log level:{}'.format(lvl))
        print_line = None
        if self.in_print and lvl >= self.print_lvl:
            print_line = self._to_print(l_time, names, msg, lvl)
            print(print_line)
        if self.remote_log.connected:
            if self.remote_log.mode == 'raw':
                print_line = self._to_print_raw(l_time, names, msg, lvl)
            elif self.remote_log.mode == 'json':
                print_line = _to_print_json(l_time, names, msg, lvl)
            else:
                print_line = print_line or self._to_print(l_time, names, msg, lvl)
            self.remote_log.msg(print_line)
        if self._app_log and lvl >= self.file_lvl:
            self._to_file(_name_builder(names), msg, lvl)

    def _to_file(self, name, msg, lvl):
        self._app_log.log(lvl, '{}: {}'.format(name, msg))

    def _str_time(self, l_time: float) -> str:
        time_str = time.strftime('%Y.%m.%d %H:%M:%S', time.localtime(l_time))
        if self.cfg['print_ms']:
            time_str += '.{:03d}'.format(int(l_time * 1000 % 1000))
        return time_str

    def _to_print(self, l_time: float, names: tuple, msg: str, lvl: int) -> str:
        str_time = self._str_time(l_time)
        return '{} {}: {}'.format(str_time, _name_builder(names, True), colored(msg, COLORS[lvl]))

    def _to_print_raw(self, l_time: float, names: tuple, msg: str, lvl: int) -> str:
        return '{} {} {}: {}'.format(self._str_time(l_time), LVL_NAME[lvl], _name_builder(names), msg)


class RemoteLogger(threading.Thread):
    REMOTE_LOG = 'remote_log'
    CHANNEL = 'net_block'

    def __init__(self, cfg, owner: Owner, log):
        super().__init__(name='RemoteLogger')
        self.cfg = cfg
        self.own = owner
        self.log = log
        self.mode = REMOTE_LOG_DEFAULT
        self._queue = queue.Queue()
        self._conn = None
        self.connected = False
        self.work = None

    def reload(self):
        self.start()
        self._queue.put_nowait(('reload', None))

    def start(self) -> None:
        if self.work is None:
            self.work = True
            self.log('start', INFO)
            super().start()

    def close_signal(self):
        if self.work is None:
            self.init(init=False)

    def join(self, timeout=5):
        self._queue.put_nowait((None, None))
        super().join(timeout=timeout)

    def run(self):
        self.init()
        while True:
            data = self._queue.get()
            if data[0] == 'msg':
                self._to_remote_log(data[1], data[2])
            elif data[0] is None:
                break
            elif data[0] == 'reload':
                self.init()
            elif data[0] == 'remote_log':
                data[1].settimeout(None)
                self._add_connect(data[1], data[2])
            else:
                self.log('Wrong data: {}'.format(repr(data)), ERROR)
        self.init(init=False)

    def msg(self, line: str):
        self._queue.put_nowait(('msg', line, self._conn))

    def _to_remote_log(self, line: str, conn):
        if conn == self._conn and self._conn.alive:
            try:
                self._conn.write(line)
            except RuntimeError:
                self._close_connect()

    def _add_remote_log(self, _, data, lock, conn):
        try:
            # Забираем сокет у сервера
            conn_ = conn.extract()
            if conn_:
                self._queue.put_nowait(('remote_log', conn_, data))
                self.start()
        finally:
            lock()

    def init(self, init=True):
        if self.cfg.gt('log', 'remote_log') and init:
            # Подписка
            self.own.subscribe(self.REMOTE_LOG, self._add_remote_log, self.CHANNEL)
        else:
            # Отписка
            self.own.unsubscribe(self.REMOTE_LOG, self._add_remote_log, self.CHANNEL)
            self._close_connect()

    def _close_connect(self):
        self.connected = False
        if self._conn:
            try:
                msg = 'CLOSE REMOTE LOG, BYE.'
                if self.mode == 'raw':
                    pass
                elif self.mode == 'json':
                    msg = _to_print_json(time.time(), ('Logger',), msg, _REMOTE)
                else:
                    msg = colored(msg, COLORS[INFO])
                self._conn.write(msg)
            except RuntimeError:
                pass
            try:
                self._conn.close()
            except RuntimeError:
                pass
            self.log('CLOSE REMOTE LOG FOR {}:{}'.format(self._conn.ip, self._conn.port), WARN)
            self._conn = None

    def _add_connect(self, conn, mode):
        self._close_connect()
        self.connected = True
        self._conn = conn
        self.mode = mode if mode in REMOTE_LOG_MODE else REMOTE_LOG_DEFAULT
        self._conn.start_remote_log()
        self.log('OPEN REMOTE LOG FOR {}:{}'.format(self._conn.ip, self._conn.port), WARN)
