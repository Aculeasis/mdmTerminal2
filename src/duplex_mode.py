#!/usr/bin/env python3

import queue
import time

import logger
from lib.socket_api_handler import SocketAPIHandler
from owner import Owner


def make_dict_reply(cmd: str or None) -> dict:
    if cmd:
        return {'result': 'ok', 'id': cmd}
    else:
        return {'method': 'ping', 'params': [str(time.time())], 'id': 'pong'}


class DuplexMode(SocketAPIHandler):
    UPGRADE_DUPLEX = 'upgrade duplex'

    def __init__(self, cfg, log, owner: Owner):
        super().__init__(cfg, log, owner, name='DuplexMode', duplex_mode=True)
        self._queue = queue.Queue()
        self.own.subscribe(self.UPGRADE_DUPLEX, self._handle_upgrade_duplex, self.UPGRADE_DUPLEX)
        self._has_started = False
        self.duplex = False
        self._notify_duplex = self.own.registration('duplex_mode')

    def start(self):
        self._has_started = True
        super().start()

    def join(self, timeout=30):
        self._queue.put_nowait(None)
        super().join(timeout=timeout)

    def send_on_socket(self, data):
        if self.duplex:
            self._conn.write(data)
        else:
            raise RuntimeError('duplex disabled')

    def off(self):
        if self.duplex:
            self._conn.close()

    def _handle_upgrade_duplex(self, _, cmd, lock, conn):
        try:
            # Забираем сокет у сервера
            conn_ = conn.extract()
            if conn_:
                conn_.settimeout(None)
                self._api_close()
                self._queue.put_nowait((conn_, cmd))
                if not self._has_started:
                    self.start()
        finally:
            lock()

    def _api_close(self):
        self.duplex = False
        self._conn.close()

    def _conn_open(self):
        self.duplex = True
        self._notify_duplex('open')

    def _conn_close(self):
        self._api_close()
        self._notify_duplex('close')

    def do_ws_allow(self, *args, **kwargs):
        return False

    def run(self):
        while self.work:
            conn = self._queue.get()
            if not conn:
                break

            self._conn, cmd = conn

            self._conn_open()
            try:
                self._processing(make_dict_reply(cmd))
            finally:
                self._conn_close()
        self._api_close()

    def _processing(self, cmd: dict):
        info = self._conn.info
        if self._testing(info, cmd):
            self.log('OPEN {}::{}:{}'.format(*info), logger.INFO)
            for line in self._conn.read():
                self.parse(line)
            self.log('CLOSE {}::{}:{}'.format(*info), logger.INFO)

    def _testing(self, info: tuple, cmd: dict) -> bool:
        try:
            self._conn.write(cmd)
        except RuntimeError as e:
            self.log('OPEN ERROR {}::{}:{}: {}'.format(*info, e), logger.ERROR)
            return False
        return True
