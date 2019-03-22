#!/usr/bin/env python3

import argparse
import base64
import cmd as cmd__
import hashlib
import json
import socket
import threading
import time
from contextlib import closing

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
GUID_STR = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionRefusedError, OSError)
CRLF = b'\r\n'


def arg_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--ip', default='127.0.0.1', help='Server IP (127.0.0.1)')
    parser.add_argument('-p', '--port', type=int, default=7575, help='Server Port (7575)')
    parser.add_argument('-t', '--token', default='hello', help='auth token ("hello")')
    return parser.parse_args()


def split_line(line: str) -> str:
    line = line.split(' ', 1)
    return line[1] if len(line) == 2 else ''


def get_headers(request_text: bytearray) -> dict:
    result = {}
    for line in request_text.split(CRLF):
        if line:
            line = line.split(b': ', 1)
            if len(line) == 2:
                result[line[0].decode()] = line[1]
    return result


def json_parse(line):
    try:
        line = json.loads(line)
    except (ValueError, TypeError) as e:
        print('Broken JSON: {}'.format(e))
        return None, None, None
    if 'error' in line:
        print('Error: {}'.format(line['error']))
        return None, None, None
    params = line.get('params')
    if isinstance(params, list) and len(params) == 1:
        params = params[0]
    else:
        params = ''
    if 'method' in line:
        return line['method'], params, line.get('id')
    if 'result' in line:
        return line.get('id'), line['result'], None
    return None, None, None


def is_http(conn: socket.socket) -> bool:
    try:
        return conn.recv(4, socket.MSG_PEEK | socket.MSG_DONTWAIT) == b'GET '
    except socket.error as e:
        print('Socket peek error: {}'.format(e))
    return False


class WebSocketServer(websocket.WebSocket):
    def __init__(self, sock, fire_cont_frame=False, enable_multithread=False, skip_utf8_validation=False, **_):
        super().__init__(fire_cont_frame, enable_multithread, skip_utf8_validation)
        self.sock = sock
        self.connected = True
        self.handshake()

    def handshake(self):
        with self.lock, self.readlock:
            old_timeout = self.sock.gettimeout()
            self.sock.settimeout(5)
            try:
                self._handshake()
            except Exception as e:
                self.shutdown()
                raise RuntimeError(e)
            self.sock.settimeout(old_timeout)

    def send_frame(self, frame):
        # A server must not mask any frames that it sends to the client.
        frame.mask = 0
        return super().send_frame(frame)

    def _handshake(self):
        def raw_send(msg):
            while msg:
                sending = self._send(msg)
                msg = msg[sending:]

        chunk_size = 1024 * 4
        max_header = 65536
        header_buffer = bytearray()
        while True:
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
                    k = key + GUID_STR
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
        self.token = data.token
        print('Server {}:{}'.format(data.ip, data.port))
        print('token: {}'.format(data.token))
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

    def send(self, data: dict or str = None):
        data = data or ''
        if isinstance(data, dict):
            data = json.dumps(data)
        with self._lock:
            data = self._send(data)
        if data:
            print('send -> {}'.format(repr(data)[1:-1]))

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

    @staticmethod
    def pong(data):
        try:
            diff_ms = int((time.time() - float(data)) * 1000)
        except (TypeError, IndexError, ValueError):
            return
        print('PING: {} ms'.format(diff_ms))

    def handler(self, client):
        stage = 0
        for line in self.reader(client):
            if self.closed:
                break
            cmd, params, id_ = json_parse(line)
            if not cmd:
                continue
            if stage == 2:
                if cmd == 'ping':
                    self.send({'result': params, 'id': id_})
                elif cmd == 'pong':
                    self.pong(params)
            elif not stage and cmd == 'authorization':
                if not self._auth(params):
                    self.send({'error': {'code': 102, 'message': 'forbidden: wrong hash'}, 'id': id_})
                else:
                    stage = 1
                    self.send({'result': 'ok', 'id': id_})
            elif stage == 1:
                if cmd == 'upgrade duplex':
                    self.send({'result': 'ok', 'id': id_})
                    stage = 2
                else:
                    self.send({'error': {'code': 101, 'message': 'I wait upgrade duplex'}, 'id': id_})
            else:
                self.send({'error': {'code': 100, 'message': 'forbidden: authorization is necessary'}, 'id': id_})
        self.close()

    def _auth(self, token) -> bool:
        if self.token:
            if not token or hashlib.sha512(self.token.encode()).hexdigest() != token:
                return False
        return True

    def reader(self, client):
        if is_http(client):
            self.ws = WebSocketServer(client, enable_multithread=True)
            print('UPGRADE: Socket -> WebSocket')
            reader = self.ws_reader()
        else:
            reader = self.tcp_reader(client)
        for line in reader:
            print('recv <- {}'.format(repr(line)[1:-1] if len(line) < 250 else '{} bytes'.format(len(line))))
            yield line

    def tcp_reader(self, client) -> str:
        client.settimeout(None)
        while self.work and not self.closed:
            with closing(client.makefile(newline='\r\n', buffering=1024 * 4)) as makefile:
                try:
                    line = makefile.readline().rstrip('\r\n')
                except (socket.timeout, UnicodeDecodeError):
                    continue
                except ERRORS:
                    break
                if not line:
                    break
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
        self.server.send({'method': 'ping', 'params': [str(time.time())], 'id': 'pong'})

    def do_exit(self, _):
        """Выход из оболочки"""
        self.server.stop()
        print('Выход.')
        return True

    def do_close(self, _):
        """Закрыть текущее соединение"""
        self.server.close()

    def do_CRLF(self, _):
        """Отправить \r\n"""
        self.server.send('\r\n')

    def do_token(self, token):
        """Сменить токен. Аргументы: токен"""
        self.server.token = token
        print('set: {}'.format(token))


if __name__ == '__main__':
    TestShell().cmdloop()
