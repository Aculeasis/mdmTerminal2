#!/usr/bin/env python3

import argparse
import base64
import cmd as cmd__
import hashlib
import http.client
import socket
import threading
import time
from io import BytesIO

import websocket

HANDSHAKE_STR = (
    "HTTP/1.1 101 Switching Protocols\r\n"
    "Upgrade: WebSocket\r\n"
    "Connection: Upgrade\r\n"
    "Sec-WebSocket-Accept: {acceptstr}\r\n\r\n"
)
FAILED_HANDSHAKE_STR = (
    "HTTP/1.1 426 Upgrade Required\r\n"
    "Upgrade: WebSocket\r\n"
    "Connection: Upgrade\r\n"
    "Sec-WebSocket-Version: 13\r\n"
    "Content-Type: text/plain\r\n\r\n"
    "This service requires use of the WebSocket protocol\r\n"
)
GUID_STR = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionRefusedError, OSError)
CRLF = b'\r\n'
WS_MARK = b'GET '


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


def get_headers(request_text):
    return http.client.parse_headers(BytesIO(request_text))


class WebSocketServer(websocket.WebSocket):
    def __init__(self, sock, init, fire_cont_frame=False, enable_multithread=False, skip_utf8_validation=False, **_):
        super().__init__(fire_cont_frame, enable_multithread, skip_utf8_validation)
        self.sock = sock
        self.connected = True
        self.handshake(init)

    def handshake(self, init_data):
        with self.lock, self.readlock:
            old_timeout = self.sock.gettimeout()
            self.sock.settimeout(5)
            try:
                self._handshake(init_data)
            except Exception as e:
                self.shutdown()
                raise RuntimeError(e)
            self.sock.settimeout(old_timeout)

    def send_frame(self, frame):
        # A server must not mask any frames that it sends to the client.
        frame.mask = 0
        return super().send_frame(frame)

    def _handshake(self, init_data):
        def raw_send(msg):
            while msg:
                sending = self._send(msg)
                msg = msg[sending:]

        chunk_size = 1024 * 4
        max_header = 65536
        header_buffer = bytearray()
        while True:
            if init_data:
                data, init_data = init_data, None
                timeout = self.sock.gettimeout()
                self.sock.settimeout(0.0)
                try:
                    data += self.sock.recv(chunk_size)
                except socket.error:
                    pass
                finally:
                    self.sock.settimeout(timeout)
            else:
                try:
                    data = self.sock.recv(chunk_size)
                except Exception as e:
                    raise RuntimeError(e)
            if not data:
                raise RuntimeError('Remote socket closed')
            # accumulate
            header_buffer.extend(data)

            if len(header_buffer) >= max_header:
                raise RuntimeError('Header exceeded allowable size')

            # indicates end of HTTP header
            if b'\r\n\r\n' in header_buffer:
                # handshake rfc 6455
                try:
                    key = get_headers(header_buffer)['Sec-WebSocket-Key']
                    k = key.encode('ascii') + GUID_STR.encode('ascii')
                    k_s = base64.b64encode(hashlib.sha1(k).digest()).decode('ascii')
                    raw_send(HANDSHAKE_STR.format(acceptstr=k_s))
                    return
                except Exception as e:
                    try:
                        raw_send(FAILED_HANDSHAKE_STR)
                    except websocket.WebSocketException:
                        pass
                    raise RuntimeError(e)


class Server(threading.Thread):
    def __init__(self, data):
        super().__init__()
        self.args = data
        self.socket = socket.socket()
        self.work = True
        self.closed = False
        self.connected = None
        self.ws = None
        self._lock = threading.Lock()
        print('Server {}:{}'.format(data.ip, data.port))
        print('username: {}'.format(data.username))
        print('password: {}'.format(data.password))
        print()

    def stop(self):
        self.work = False
        self.close()
        self.join(20)

    def _ws_close(self):
        try:
            self.ws.close()
        except websocket.WebSocketException:
            pass

    def _sock_close(self):
        self.connected.sendall(CRLF*2)
        self.connected.close()

    def close(self):
        with self._lock:
            if self.ws:
                self._ws_close()
            elif self.connected:
                self._sock_close()
            self.ws = None
            self.connected = None
            self.closed = True

    def send(self, data: str = ''):
        with self._lock:
            data = self._send(data)
        if data:
            print('send -> {}'.format(data))

    def _send(self, data: str) -> str:
        if not self.connected:
            return 'no clients' if data else ''
        else:
            try:
                if not data:
                    self.close()
                elif self.ws:
                    self.ws.send(data)
                else:
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
            self.closed = False
            self.connected = client
            try:
                self.handler(client)
            except Exception as e:
                print('ERROR: {}'.format(e))
            finally:
                self.connected = None
                self.closed = True
                print('Disconnected {}:{}.'.format(*address))
                client.close()
        print()
        print('BYE!')
        self.socket.close()

    def broken(self, msg: str = ''):
        if msg:
            self.send('BROKEN {}'.format(msg))
        print('=== Broken handshake ===')

    @staticmethod
    def pong(line: str):
        try:
            diff_ms = int((time.time() - float(line.split(':', 1)[1])) * 1000)
        except (TypeError, IndexError, ValueError):
            return
        print('PING: {} ms'.format(diff_ms))

    def handler(self, client):
        stage = 0

        for line in self.reader(client):
            if self.closed:
                break
            line_l = line.lower()
            if stage == 3:
                if line_l.startswith('ping:'):
                    data = line_l.split(':', 1)
                    data[0] = 'pong'
                    self.send(':'.join(data))
                elif line_l.startswith('pong:'):
                    self.pong(line)
                continue
            if not stage and line_l == 'upgrade duplex':
                print('=== Start handshake ===')
                self.send('say THIS IS TEST SERVER!')
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
        self.close()

    def reader(self, client):
        data = b''
        first = True
        while self.work and not self.closed:
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
                if first and line.startswith(WS_MARK):
                    self.ws = WebSocketServer(client, data, enable_multithread=True)
                    print('UPGRADE: Socket -> WebSocket')
                    for line in self.ws_reader():
                        yield line
                    return
                try:
                    line = line.decode()
                except UnicodeDecodeError:
                    continue

                print('recv <- {}'.format(line))
                yield line

    def ws_reader(self):
        while self.ws.connected and self.work and not self.closed:
            try:
                line = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except websocket.WebSocketException:
                break
            if not line:
                continue
            print('recv <- {}'.format(line))
            yield line


class TestShell(cmd__.Cmd):
    intro = 'Welcome to the test shell. Type help or ? to list commands.\n'
    prompt = ''

    def __init__(self):
        super().__init__()
        self.server = Server(arg_parser())
        self.server.start()

    def default(self, line):
        if line:
            self.server.send(line)

    def do_ping(self, _):
        """Ping."""
        self.server.send('ping:{}'.format(time.time()))

    def do_exit(self, _):
        """Выход из оболочки"""
        self.server.stop()
        print('Выход.')
        return True

    def do_close(self, _):
        """Закрыть текущее соединение"""
        self.server.close()


if __name__ == '__main__':
    TestShell().cmdloop()
