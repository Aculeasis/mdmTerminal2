
import hashlib
import json
import os
import threading
import time

import logger
from lib.socket_api_handler import upgrade_duplex
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
            proto, *address = _get_address(outgoing_socket)
        except RuntimeError as e:
            self.log('outgoing_socket: {}'.format(e), logger.CRIT)
            return False

        address = tuple([proto.upper()] + address)
        try:
            soc = create_connection(proto, *address[1:])
        except RuntimeError as e:
            self.log('Connect to {}::{}:{}: {}'.format(*address, e), logger.ERROR)
            return False

        token = self.cfg['token']
        hash_ = hashlib.sha3_512(token.encode() if token else os.urandom(64)).hexdigest()
        stage = 1
        try:
            soc.write('authorization:{}'.format(hash_))
            for line in soc.read():
                try:
                    if stage == 1:
                        self._check_stage_1(line)
                        self.log('Authorized {}::{}:{}'.format(*address), logger.INFO)
                        stage = 2
                        soc.write('upgrade duplex')
                    else:
                        if line.lower() != 'upgrade duplex ok':
                            raise ValueError('Surprise: {}'.format(repr(line)))
                        soc.auth = True
                        upgrade_duplex(self.own, soc)
                        self.log('Upgrade duplex ok {}::{}:{}'.format(*address), logger.INFO)
                        # FIXME: race condition
                        time.sleep(0.1)
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
    def _check_stage_1(line):
        data = json.loads(line)
        if not isinstance(data, dict):
            raise ValueError('Not a dict: {}'.format(type(data)))
        cmd = data.get('cmd', 'Unset')
        code = data.get('code', -1)
        if cmd.lower() != 'authorization':
            raise ValueError('Surprise: {}'.format(repr(data)))
        if code:
            raise RuntimeError('Authorization failed: {} [{}] {}'.format(cmd, code, data.get('msg', '')))
