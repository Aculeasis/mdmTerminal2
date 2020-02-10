#!/usr/bin/env python3

import errno
import socket

MULTICAST_TTL = 15
TIMEOUT = 10
BUFFER_SIZE = 1024 * 2
RESPONSE_URI = 'mdmt2'
CRLF = b'\r\n'
REQUEST = CRLF.join([
    b'M-SEARCH * HTTP/1.1',
    b'Host:239.255.255.250:1900',
    b'ST:rn:schemas-upnp-org:service:mdmTerminal2',
    b'Man:"ssdp:discover"',
    b'MX:1', b'', b''
])


class DiscoveryClient:
    def __init__(self, ip='0.0.0.0', server_port=1900, client_port=9999, group='239.255.255.250', broadcast=False):
        self._sendto = ('255.255.255.255' if broadcast else group, server_port)
        self._client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass
        except socket.error as e:
            if e.errno != errno.ENOPROTOOPT:
                raise
        if broadcast:
            self._client.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        else:
            self._client.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL)
        self._client.bind((ip, client_port))
        self._client.settimeout(TIMEOUT)

    def run_forever(self):
        self._client.sendto(REQUEST, self._sendto)
        is_printing = False
        while True:
            try:
                msg, address = self._client.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                self._client.sendto(REQUEST, self._sendto)
                if is_printing:
                    print('=' * 30)
                is_printing = False
                continue
            headers = get_headers(msg)
            if headers.get('URI') == RESPONSE_URI:
                is_printing = True
                if 'Server' in headers:
                    print('{} {}'.format(headers.get('AL', '{}:{}'.format(*address)), headers['Server']))
                else:
                    print(repr(msg.rstrip(b'\0')))


def get_headers(msg: bytes) -> dict:
    headers = {}
    for key_val in [line.split(b':', 1) for line in msg.rstrip(b'\0').split(CRLF * 2, 1)[0].split(CRLF)]:
        if len(key_val) == 2 and key_val[0]:
            headers[key_val[0].decode()] = key_val[1].decode()
    return headers


if __name__ == '__main__':
    client = DiscoveryClient()
    client.run_forever()
