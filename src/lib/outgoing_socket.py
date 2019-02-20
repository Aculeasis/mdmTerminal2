import socket
import threading
import time

import logger
from lib.socket_wrapper import Connect
from lib.upgrade_duplex import UpgradeDuplexHandshake
from owner import Owner


def _get_address(outgoing_socket: str) -> tuple:
    try:
        ip, port = outgoing_socket.split(':', 1)
        port = int(port)
        if port < 1:
            raise ValueError('port must be positive integer: {}'.format(port))
    except (ValueError, TypeError) as e:
        raise RuntimeError(e)
    return ip, port


class OutgoingSocket(threading.Thread):
    INTERVAL = 60
    EVENT = 'duplex_mode'

    def __init__(self, cfg: dict, log, own: Owner):
        super().__init__(name='OutgoingSocket')
        self.cfg = cfg
        self.log = log
        self.own = own
        self.work = False
        self._connected = False
        self._wait = threading.Event()

    def _duplex_mode_event(self, cmd, state, *_):
        if cmd == self.EVENT:
            if state == 'close':
                self._connected = False
            elif state == 'open':
                self._connected = True
            self._wait.set()

    def reload(self):
        self._wait.set()

    def start(self):
        if not self.work:
            self.work = True
            self.own.subscribe(self.EVENT, self._duplex_mode_event)
            super().start()

    def join(self, timeout=None):
        if self.work:
            self.work = False
            self.own.unsubscribe(self.EVENT, self._duplex_mode_event)
            self._wait.set()
            super().join(timeout)

    def run(self):
        while self.work:
            self._connect()
            sleep_time = self.INTERVAL
            while self.work and (self._connected or sleep_time > 0):
                self._wait.clear()
                s_time = time.time()
                self._wait.wait(self.INTERVAL)
                if sleep_time > 0:
                    sleep_time -= (time.time() - s_time)

    def _connect(self) -> bool:
        outgoing_socket = self.cfg['outgoing_socket']
        # FIXME: race condition
        time.sleep(0.1)
        if not outgoing_socket or self.own.duplex_mode_on:
            return False
        try:
            address = _get_address(outgoing_socket)
        except RuntimeError as e:
            self.log('outgoing_socket: {}'.format(e), logger.CRIT)
            return False

        soc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        soc.settimeout(10)

        try:
            soc.connect(address)
        except (BrokenPipeError, ConnectionResetError, ConnectionRefusedError, OSError) as e:
            self.log('Connect to {}:{}: {}'.format(*address, e), logger.ERROR)
            return False

        soc = Connect(soc, address, lambda *_, **__: False)
        upgrade = UpgradeDuplexHandshake(self.cfg, self.log, self.own, soc, incoming=False)
        try:
            upgrade.outgoing()
            if upgrade.success:
                # FIXME: race condition
                time.sleep(0.1)
        finally:
            soc.close()
        return upgrade.success
