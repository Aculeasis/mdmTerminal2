#!/usr/bin/env python3

import socket

import logger as logger_
from languages import SERVER as LNG
from lib.socket_api_handler import SocketAPIHandler
from lib.upgrade_duplex import UpgradeDuplexHandshake
from owner import Owner


class MDTServer(SocketAPIHandler):
    def __init__(self, cfg, log, owner: Owner):
        super().__init__(cfg, log, owner, name='MDTServer')
        self._local = ('', 7999)
        self._socket = socket.socket()

    def do_ws_allow(self, ip, port, token):
        ws_token = self._cfg.gt('system', 'ws_token')
        allow = ws_token and ws_token == token
        msg = '{} upgrade socket to webSocket from {}:{}'.format('Allow' if allow else 'Ignore', ip, port)
        self.log(msg, logger_.DEBUG if allow else logger_.WARN)
        if allow and ws_token == 'token_is_unset':
            self.log('WebSocket token is unset, it is very dangerous!', logger_.WARN)
        return allow

    def _open_socket(self) -> bool:
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.settimeout(1)
        try:
            self._socket.bind(self._local)
        except OSError as e:
            say = LNG['err_start_say'].format(LNG['err_already_use'] if e.errno == 98 else '')
            self.log(LNG['err_start'].format(*self._local, e), logger_.CRIT)
            self.own.say(say)
            return False
        self._socket.listen(1)
        return True

    def run(self):
        upgrade = None
        if not self._open_socket():
            return
        while self.work:
            try:
                self._conn.insert(*self._socket.accept())
                self._conn.settimeout(5.0)
            except socket.timeout:
                continue
            allow = self._cfg.allow_connect(self._conn.ip)
            msg = '{} new connection from {}:{}'.format('Allow' if allow else 'Ignore', self._conn.ip, self._conn.port)
            self.log(msg, logger_.DEBUG if allow else logger_.WARN)
            try:
                if not allow:
                    continue
                for line in self._conn.read():
                    if upgrade:
                        upgrade(line)
                        continue
                    if line == 'upgrade duplex':
                        upgrade = UpgradeDuplexHandshake(self._cfg, self.log.add('I'), self.own, self._conn)
                        continue
                    self._parse(line)
            finally:
                upgrade = None
                self._conn.close()
        self._socket.close()


class DummyServer:
    def start(self):
        pass

    def join(self, *args, **kwargs):
        pass


def server_constructor(cfg, logger, owner: Owner, old=None) -> MDTServer or DummyServer:
    on = not cfg.gt('smarthome', 'disable_server')

    if old is None:
        old = MDTServer(cfg=cfg, log=logger.add('Server'), owner=owner) if on else DummyServer()
    if isinstance(old, DummyServer):
        old = MDTServer(cfg=cfg, log=logger.add('Server'), owner=owner) if on else old
        old.start()
    elif isinstance(old, MDTServer):
        if not on:
            old.join(20)
            old = DummyServer()
    else:
        raise TypeError('Wrong type: {}'.format(type(old)))
    return old
