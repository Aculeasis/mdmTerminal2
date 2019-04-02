#!/usr/bin/env python3

import socket

MULTICAST_TTL = 15
REQUEST_MARK = b'mdmt2_recv'
RESPONSE_MARK = b'mdmt2_send'
BUFFER_SIZE = 64
LF = b'\n'


class DiscoveryClient:
    def __init__(self, ip='', server_port=7999, client_port=9999, group='239.2.3.1'):
        self._sendto = (group, server_port)
        self._client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._client.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL)
        self._client.bind((ip, client_port))
        self._client.settimeout(10)

    def _request(self):
        self._client.sendto(REQUEST_MARK, socket.SOCK_NONBLOCK, self._sendto)

    def run_forever(self):
        self._request()
        while True:
            try:
                msg, address = self._client.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                self._request()
                continue
            if msg.startswith(RESPONSE_MARK):
                msg = msg.rstrip(b'\0').split(LF)
                try:
                    msg = 'version: {}; uptime: {} seconds'.format(msg[1].decode(), int(msg[2].decode()))
                except (ValueError, UnicodeDecodeError, IndexError, TypeError) as e:
                    msg = 'error parsing {}: {}'.format(repr(msg), e)
                print('mdmTerminal2 address: {}:{}; {}'.format(*address, msg))


if __name__ == '__main__':
    client = DiscoveryClient()
    client.run_forever()
