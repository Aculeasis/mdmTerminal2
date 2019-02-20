#!/usr/bin/env python3

import argparse
import cmd as cmd__
import socket
import threading

ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionRefusedError, OSError)
CRLF = b'\r\n'


def arg_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--ip', default='127.0.0.1', help='Server IP (127.0.0.1)')
    parser.add_argument('-p', '--port', type=int, default=7575, help='Server Port (7575)')
    parser.add_argument('-u', '--username', default='root', help='username ("root")')
    parser.add_argument('-a', '--password', default='toor', help='password ("toor")')
    return parser.parse_args()


def split_line(line: str) -> str:
    line = line.split(' ', 1)
    return line[1] if len(line) == 2 else ''


class Server(threading.Thread):
    def __init__(self, data):
        super().__init__()
        self.args = data
        self.socket = socket.socket()
        self.work = True
        self.close = False
        self.connected = None
        self._lock = threading.Lock()
        print('Server {}:{}'.format(data.ip, data.port))
        print('username: {}'.format(data.username))
        print('password: {}'.format(data.password))
        print()

    def stop(self):
        self.close = True
        self.work = False
        self.join(20)

    def send(self, data: str = ''):
        data = self._send(data)
        if data:
            print('send -> {}'.format(data))

    def _send(self, data: str) -> str:
        if not self.connected:
            return 'no clients'
        else:
            try:
                with self._lock:
                    self.connected.sendall(data.encode() + CRLF)
            except Exception as e:
                return 'ERROR: {}'.format(e)
            return data

    def run(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.settimeout(1)
        self.socket.bind((self.args.ip, self.args.port))
        self.socket.listen(1)
        print('GO!')
        while self.work:
            try:
                client, address = self.socket.accept()
            except socket.timeout:
                continue
            client.settimeout(2)
            print()
            print('Connected {}:{} ...'.format(*address))
            self.close = False
            self.connected = client
            try:
                self.handler(client)
            except Exception as e:
                print('ERROR: {}'.format(e))
            finally:
                self.connected = None
                self.close = True
                print('Disconnected {}:{}.'.format(*address))
                client.close()
        print()
        print('BYE!')
        self.socket.close()

    def broken(self, msg: str = ''):
        if msg:
            self.send('BROKEN {}'.format(msg))
        print('=== Broken handshake ===')

    def handler(self, client):
        stage = 0

        self.send('say THIS IS TEST SERVER!')
        for line in self.reader(client):
            if self.close:
                break
            line_l = line.lower()
            if stage == 3:
                if line_l.startswith('ping:'):
                    data = line_l.split(':', 1)
                    data[0] = 'pong'
                    self.send(':'.join(data))
                continue
            if not stage and line_l == 'upgrade duplex':
                print('=== Start handshake ===')
                if self.args.username:
                    self.send('LOGIN')
                    stage = 1
                elif self.args.password:
                    self.send('PASSWORD')
                    stage = 2
                else:
                    stage = 3
                    self.send('upgrade duplex ok')
            elif stage == 1 and line_l.startswith('login'):
                login = split_line(line)
                if self.args.username and self.args.username != login:
                    self.broken('wrong login: {}'.format(login))
                    break
                elif self.args.password:
                    self.send('PASSWORD')
                    stage = 2
                else:
                    stage = 3
                    self.send('upgrade duplex ok')
                    print('=== End handshake ===')
            elif stage == 2 and line_l.startswith('password'):
                password = split_line(line)
                if not password or password != self.args.password:
                    self.broken('WRONG PASSWORD: {}'.format(password))
                    break
                stage = 3
                self.send('upgrade duplex ok')
                print('=== End handshake ===')
            elif line_l.startswith('broken'):
                self.broken()
                break
            elif line_l.startswith('say'):
                print('SAY: {}'.format(line[3:].lstrip()))
        self.send()

    def reader(self, client):
        data = b''
        while self.work and not self.close:
            try:
                chunk = client.recv(1024)
            except socket.timeout:
                continue
            except ERRORS:
                break
            if not chunk:
                break
            data += chunk
            while CRLF in data:
                line, data = data.split(CRLF, 1)
                if not line:
                    return
                try:
                    line = line.decode()
                except UnicodeDecodeError:
                    continue
                print('recv <- {}'.format(line))
                yield line


class TestShell(cmd__.Cmd):
    intro = 'Welcome to the test shell. Type help or ? to list commands.\n'
    prompt = '~# '

    def __init__(self):
        super().__init__()
        self.server = Server(arg_parser())
        self.server.start()

    def default(self, line):
        self.server.send(line)

    def do_exit(self, _):
        """Выход из оболочки"""
        self.server.stop()
        print('Выход.')
        return True

    def do_close(self, _):
        """Закрыть текущее соединение"""
        self.server.send()
        self.server.close = True


if __name__ == '__main__':
    TestShell().cmdloop()
