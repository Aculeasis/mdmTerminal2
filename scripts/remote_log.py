#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import socket


def log(ip, port):
    crlf = b'\r\n'
    client = socket.create_connection((ip, port))
    client.send(b'remote_log' + crlf * 2)
    data = b''
    chunk = True
    while chunk:
        chunk = client.recv(1024)
        data += chunk
        while crlf in data:
            line, data = data.split(crlf, 1)
            if not line:
                return
            print(line.decode('utf-8'))


if __name__ == '__main__':
    log(sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1', int(sys.argv[2]) if len(sys.argv) > 2 else 7999)
