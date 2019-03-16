#!/usr/bin/env python3

import queue
import time

import logger
from lib.socket_api_handler import SocketAPIHandler
from owner import Owner


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

    def join(self, timeout=None):
        self._queue.put_nowait(None)
        super().join(timeout)

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

    def do_ws_allow(self, *args, **kwargs):
        return False

    def run(self):
        while self.work:
            conn = self._queue.get()
            if not conn:
                break

            self._conn, cmd = conn
            info = (self._conn.proto.upper(), self._conn.ip, self._conn.port)
            self.duplex = True
            self._notify_duplex('open')
            if cmd:
                cmd = {'result': 'ok', 'id': cmd}
            else:
                cmd = {'method': 'ping', 'params': [str(time.time())], 'id': 'pong'}
            try:
                self._conn.write(cmd)
            except RuntimeError as e:
                self._api_close()
                self.log('OPEN ERROR {}::{}:{}: {}'.format(*info, e), logger.ERROR)
                self._notify_duplex('close')
                continue
            else:
                self.log('OPEN {}::{}:{}'.format(*info), logger.INFO)

            try:
                for line in self._conn.read():
                    self.parse(line)
            finally:
                self._api_close()
                self.log('CLOSE {}::{}:{}'.format(*info), logger.INFO)
                self._notify_duplex('close')
        self._api_close()
