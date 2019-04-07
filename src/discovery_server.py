import errno
import socket
import struct
import threading
import uuid

import logger

TIMEOUT = 1.0
BUFFER_SIZE = 1024 * 2
M_SEARCH = b'M-SEARCH'
NOTIFY = b'NOTIFY'
SERVICE_NAME = 'mdmt2'
REPLY = 'HTTP/1.1 200 OK\r\nCACHE-CONTROL:max-age=1800\r\n' \
        'ST:{service}\r\nURI:{service}\r\nUSN:uuid:{uuid}\r\nEXT:\r\n'.format(
            service=SERVICE_NAME, uuid=uuid.uuid3(uuid.NAMESPACE_DNS, SERVICE_NAME))
REPLY += 'Server:{server}\r\nAL:{location}\r\n\r\n'
SERVER_PORT = 7999


class DiscoveryServer(threading.Thread):
    def __init__(self, cfg, log, ip='', port=1900, multicast_group='239.255.255.250'):
        super().__init__()
        self.cfg = cfg
        self.log = log
        self._address = (ip, port)
        self._work = False
        self._server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        multicast_req = struct.pack('4sl', socket.inet_aton(multicast_group), socket.INADDR_ANY)
        self._server.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, multicast_req)

    def start(self):
        try:
            try:
                self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except AttributeError:
                pass
            except socket.error as e:
                if e.errno != errno.ENOPROTOOPT:
                    raise
            self._server.bind(self._address)
            self._server.settimeout(TIMEOUT)
        except Exception as e:
            self.log('Binding error: {}'.format(e), logger.ERROR)
        else:
            self._work = True
            super().start()
            self.log('start', logger.INFO)

    def join(self, timeout=20):
        if self._work:
            self._work = False
            self.log('stopping...')
            super().join(timeout)
            self._server.close()
            self.log('stop.', logger.INFO)

    def run(self):
        while self._work:
            try:
                msg, address = self._server.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                continue
            except socket.error as e:
                self.log('Socket error: {}'.format(e), logger.ERROR)
                continue
            if msg.startswith(M_SEARCH):
                server = 'mdmTerminal2 version {}; uptime {} seconds'.format(self.cfg.version_str, self.cfg.uptime)
                location = '{}:{}'.format(self.cfg.gts('ip'), SERVER_PORT)
                reply = REPLY.format(server=server, location=location).encode()
                try:
                    self._server.sendto(reply, address)
                except Exception as e:
                    self.log('Reply sending error to {}:{}: {}'.format(*address, e), logger.WARN)
            elif not msg.startswith(NOTIFY):
                self.log('Wrong request from {}:{}: {}'.format(*address, repr(msg.rstrip(b'\0'))))
