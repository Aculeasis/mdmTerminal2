
import hashlib
import json
import os
import threading
import time

import logger
from duplex_mode import DuplexInstance
from lib.socket_wrapper import create_connection
from owner import Owner


def _get_address(outgoing_socket: str) -> tuple:
    try:
        data = [x for x in outgoing_socket.split(':') if x]
        if len(data) == 3:
            proto, ip, port = data
            proto = proto.lower()
        else:
            proto, (ip, port) = 'tcp', data
        if proto not in ('tcp', 'tls', 'ws', 'wss'):
            raise ValueError('Unknown protocol: {}'.format(proto))
        port = int(port)
        if port < 1:
            raise ValueError('port must be positive integer: {}'.format(port))
    except (ValueError, TypeError) as e:
        raise RuntimeError(e)
    return proto, ip, port


class OutgoingSocket(threading.Thread):
    INTERVAL = 60

    def __init__(self, cfg, log, own: Owner):
        super().__init__(name='OutgoingSocket')
        self.cfg = cfg
        self.log = log
        self.own = own
        self.work = False
        self._connected = False
        self._wait = threading.Event()
        self._duplex = None
        self._outgoing_socket = None

    def _close_callback(self):
        self._connected = False
        self._wait.set()

    def reload(self):
        self._set_outgoing_socket()
        self._wait.set()

    def start(self):
        self._set_outgoing_socket()
        if not self.work:
            self.work = True
            super().start()

    def join(self, timeout=None):
        if self.work:
            self.work = False
            self._wait.set()
            super().join(timeout=timeout)

    def _close_duplex(self):
        if self._duplex:
            self._connected = False
            self._duplex.join()
            self._duplex = None

    def _start_duplex(self, address: tuple, conn):
        conn.auth = True
        self._connected = True
        name = '{}::{}:{}'.format(*address)
        self._duplex = DuplexInstance(
            self.cfg, self.log.add(name), self.own, name, conn.extract(), '', self._close_callback
        )
        self.log('Upgrade duplex ok {}'.format(name), logger.INFO)

    def _set_outgoing_socket(self):
        outgoing_socket = self.cfg.gt('smarthome', 'outgoing_socket')
        if outgoing_socket != self._outgoing_socket:
            self._outgoing_socket = outgoing_socket
            self._connected = False

    def run(self):
        while self.work:
            self._close_duplex()
            self._connect()
            sleep_time = self.INTERVAL if not self._connected else 0
            while self.work and (self._connected or sleep_time > 0):
                self._wait.clear()
                s_time = time.time()
                self._wait.wait(self.INTERVAL)
                if sleep_time > 0:
                    sleep_time -= (time.time() - s_time)
        self._close_duplex()

    def _connect(self) -> bool:
        if not self._outgoing_socket:
            return False
        try:
            proto, *address = _get_address(self._outgoing_socket)
        except RuntimeError as e:
            self.log('outgoing_socket: {}'.format(e), logger.CRIT)
            return False

        address = tuple([proto.upper()] + address)
        try:
            soc = create_connection(proto, *address[1:])
        except RuntimeError as e:
            self.log('Connect to {}::{}:{}: {}'.format(*address, e), logger.ERROR)
            return False

        token = self.cfg.gt('smarthome', 'token')
        hash_ = hashlib.sha512(token.encode() if token else os.urandom(64)).hexdigest()
        stage = 1
        try:
            soc.write({'method': 'authorization', 'params': [hash_], 'id': 'authorization'})
            for line in soc.read():
                try:
                    if stage == 1:
                        self._check_stage(line, 'authorization')
                        self.log('Authorized {}::{}:{}'.format(*address), logger.INFO)
                        stage = 2
                        soc.write({'method': 'upgrade duplex', 'id': 'upgrade duplex'})
                    else:
                        self._check_stage(line, 'upgrade duplex')
                        self._start_duplex(address, soc)
                        return True
                except (ValueError, TypeError) as e:
                    self.log('Wrong reply {}::{}:{}: {}'.format(*address, e), logger.WARN)
                    continue
        except RuntimeError as e:
            self.log('Error {}::{}:{}: {}'.format(*address, e), logger.ERROR)
        finally:
            soc.close()
        return False

    @staticmethod
    def _check_stage(line, id_):
        data = json.loads(line)
        if not isinstance(data, dict):
            raise ValueError('Not a dict: {}'.format(type(data)))
        if data.get('id') != id_:
            raise ValueError('Surprise: {}'.format(repr(data)))
        if 'error' in data:
            msg = 'Failed {}: [{}] {}'.format(id_, data['error'].get('code'), data['error'].get('message'))
            raise RuntimeError(msg)
