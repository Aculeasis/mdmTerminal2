import socket
import struct
import threading

import logger

REQUEST_MARK = b'mdmt2_recv'
RESPONSE_MARK = b'mdmt2_send'
BUFFER_SIZE = 64
LF = b'\n'


class DiscoveryServer(threading.Thread):
    def __init__(self, cfg, log, ip='', port=7999, multicast_group='239.2.3.1'):
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
            self._server.bind(self._address)
        except Exception as e:
            self.log('Binding error: {}'.format(e), logger.ERROR)
            return
        self._server.settimeout(1.0)
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
            if msg.startswith(REQUEST_MARK):
                version = self.cfg.version_str.encode()
                uptime = str(self.cfg.uptime).encode()
                reply = LF.join((RESPONSE_MARK, version, uptime))
                try:
                    self._server.sendto(reply, socket.SOCK_NONBLOCK, address)
                except Exception as e:
                    self.log('Reply sending error to {}:{}: {}'.format(*address, e), logger.WARN)
                else:
                    self.log('Reply sent to {}:{}'.format(*address))
