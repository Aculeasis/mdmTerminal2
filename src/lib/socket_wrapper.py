#!/usr/bin/env python3
"""
The MIT License (MIT)
Copyright (c) 2013 Dave P. https://github.com/dpallot/simple-websocket-server

This code was modified by Aculeasis, 2019
"""

import base64
import hashlib
import json
import socket
import ssl
import threading
import time
from contextlib import closing

import websocket  # pip install websocket-client

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
    "This service requires use of the WebSocket protocol or raw TCP/IP\r\n\r\n"
    "See https://github.com/Aculeasis/mdmTerminal2/wiki/API-(draft)\r\n"
)

GUID_STR = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


CRLF = b'\r\n'
AUTH_FAILED = 'Terminal rejected connection (incorrect ws_token?). BYE!'
ALL_EXCEPTS = (OSError, websocket.WebSocketException, TypeError, ValueError, AttributeError)


def is_http(conn: socket.socket) -> bool:
    try:
        return conn.recv(4, socket.MSG_PEEK | socket.MSG_DONTWAIT) == b'GET '
    except socket.error:
        pass
    return False


def get_headers(request_text: bytearray) -> dict:
    result = {}
    for line in request_text.split(CRLF):
        if line:
            line = line.split(b': ', 1)
            if len(line) == 2:
                result[line[0].decode()] = line[1]
    return result


class Connect:
    CHUNK_SIZE = 1024 * 4

    def __init__(self, conn, ip_info, ws_allow, auth=False):
        self._conn = conn
        self._is_ws = isinstance(conn, websocket.WebSocket)
        self._ip_info = ip_info
        self._ws_allow = ws_allow
        self.auth = auth
        self._send_lock = threading.Lock()
        self._recv_lock = threading.Lock()

    @property
    def proto(self) -> str:
        def select_type(target, names):
            if isinstance(target, ssl.SSLSocket):
                return names[1]
            elif isinstance(target, socket.socket):
                return names[0]
            else:
                return str(type(target))

        if not self._conn:
            return 'NaN'
        elif self._is_ws:
            return select_type(self._conn.sock, ('ws', 'wss'))
        else:
            return select_type(self._conn, ('tcp', 'tls'))

    @property
    def ip(self):
        return self._ip_info[0] if self._ip_info else None

    @property
    def port(self):
        return self._ip_info[1] if self._ip_info else None

    def settimeout(self, timeout):
        if self._conn:
            self._conn.settimeout(timeout)

    def extract(self):
        if self._conn:
            try:
                return Connect(self._conn, self._ip_info, self._ws_allow, self.auth)
            finally:
                self._conn = None
                self._ip_info = None
                self.auth = False

    def insert(self, conn, ip_info):
        self._conn = conn
        self._is_ws = isinstance(conn, websocket.WebSocket)
        self._ip_info = ip_info
        self.auth = False

    def start_remote_log(self):
        """
        Нельзя просто так взять и закрыть веб-сокет.
        """
        if self._is_ws and self._conn.poll is None:
            self._conn.poll = WebSocketCap(self._conn)

    def close(self):
        if self._conn:
            self._ws_close() if self._is_ws else self._tcp_close()
        self.auth = False

    def _tcp_close(self):
        try:
            # Сообщаем серверу о завершении сеанса отправкой \r\n\r\n
            self._tcp_write(CRLF)
        except RuntimeError:
            pass
        try:
            self._conn.close()
        except AttributeError:
            pass

    def _ws_close(self):
        try:
            self._conn.close(timeout=0.5)
        except ALL_EXCEPTS:
            pass

    def write(self, data):
        """
        Преобразует dict -> json, str -> bytes, (nothing) -> bytes('') и отправляет байты в сокет.
        В конце автоматически добавляет \r\n.
        Если это веб-сокет то кидаем все в str.
        В любой непонятной ситуации кидает RuntimeError.
        """
        if not self._conn:
            return
        if not data:
            data = ''
        elif isinstance(data, (dict, list)):
            try:
                data = json.dumps(data, ensure_ascii=False)
            except TypeError as e:
                raise RuntimeError(e)

        with self._send_lock:
            self._ws_write(data) if self._is_ws else self._tcp_write(data)

    def _tcp_write(self, data: str or bytes):
        if isinstance(data, str):
            data = data.encode()
        elif not isinstance(data, bytes):
            raise RuntimeError('Unsupported data type: {}'.format(repr(type(data))))
        data += CRLF
        timeout = 0
        while data:
            try:
                sending = self._conn.send(data)
            except socket.timeout as e:
                timeout += 1
                if timeout > 5:
                    raise RuntimeError(e)
                time.sleep(0.1)
                continue
            except (socket.error, AttributeError) as e:
                raise RuntimeError(e)
            timeout = 0
            data = data[sending:]

    def _ws_write(self, data: str or bytes):
        if isinstance(data, bytes):
            data = data.decode()
        elif not isinstance(data, str):
            raise RuntimeError('Unsupported data type: {}'.format(repr(type(data))))
        if self._conn.auth:
            try:
                self._conn.send(data)
            except ALL_EXCEPTS as e:
                raise RuntimeError(e)

    def read(self):
        """
        Генератор,
        читает байты из сокета, разделяет их по \r\n и возвращает результаты в str,
        получение пустых данных(\r\n\r\n), любая ошибка сокета или завершение работы прерывает итерацию.
        Для совместимости: Если в данных вообще не было \r\n, сделаем вид что получили <data>\r\n\r\n.
        При получении `GET ` первой командой превращает сокет в веб-сокет.
        """
        if not self._conn:
            return
        with self._recv_lock:
            if self._is_ws:
                return self._ws_read()
            if not self.auth and is_http(self._conn):
                self.insert(WSServerAdapter(self._conn, self.CHUNK_SIZE), self._ip_info)
                return self._ws_read()
            return self._tcp_read()

    def _tcp_read(self):
        with closing(self._conn.makefile(newline='\r\n', buffering=self.CHUNK_SIZE)) as makefile:
            while self._conn:
                try:
                    line = makefile.readline().rstrip('\r\n')
                except OSError:
                    break
                except UnicodeDecodeError:
                    continue
                if not line:
                    break
                yield line

    def _ws_read(self):
        while self._conn:
            try:
                chunk = self._conn.recv()
            except ALL_EXCEPTS:
                break
            if chunk is None:
                continue
            if not self._conn.auth:
                if not self._ws_auth(chunk):
                    return
                continue
            yield chunk

    def _ws_auth(self, chunk) -> bool:
        if self._ws_allow(self.ip, self.port, chunk):
            self._conn.auth = True
            return True
        try:
            self._conn.send(AUTH_FAILED)
        except ALL_EXCEPTS:
            pass
        self.close()
        return False


class WebSocketCap(threading.Thread):
    def __init__(self, ws):
        super().__init__()
        self._ws = ws
        self.start()

    def run(self):
        while self._ws.connected:
            try:
                self._ws.recv()
            except websocket.WebSocketTimeoutException:
                pass
            except ALL_EXCEPTS:
                break
            time.sleep(0.3)


class WSClientAdapter(websocket.WebSocket):
    def __init__(self, get_mask_key=None, sockopt=None, sslopt=None, fire_cont_frame=False, enable_multithread=False,
                 skip_utf8_validation=False, **_):
        super().__init__(get_mask_key, sockopt, sslopt, fire_cont_frame, enable_multithread, skip_utf8_validation)

        self.poll = None
        self.auth = False

    def recv(self):
        with self.readlock:
            opcode, data = self.recv_data()
        if opcode == websocket.ABNF.OPCODE_TEXT:
            return data.decode("utf-8")
        else:
            return None


class WSServerAdapter(WSClientAdapter):
    def __init__(self, conn, chunk_size=1024*4):
        super().__init__()
        self.sock = conn
        self.connected = True
        with self.readlock, self.lock:
            timeout = self.sock.gettimeout()
            self.sock.settimeout(10)
            try:
                self._handshake(chunk_size)
            except Exception as e:
                self.shutdown()
                raise RuntimeError(e)
            self.sock.settimeout(timeout)

    def send_frame(self, frame):
        # A server must not mask any frames that it sends to the client.
        frame.mask = 0
        return super().send_frame(frame)

    def _handshake(self, chunk_size):
        def raw_send(msg):
            while msg:
                sending = self._send(msg)
                msg = msg[sending:]

        max_header = 65536
        header_buffer = bytearray()
        while True:
            try:
                data = self.sock.recv(chunk_size)
            except Exception as e:
                raise RuntimeError(e)

            if not data:
                raise RuntimeError('remote socket closed')
            # accumulate
            header_buffer.extend(data)

            if len(header_buffer) >= max_header:
                raise RuntimeError('header exceeded allowable size')

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
                    raise RuntimeError('handshake failed: {}'.format(e))


def create_connection(proto: str, ip: str, port: int) -> Connect:
    proto = proto.lower()
    soc = ws_maker(proto, ip, port) if proto in ('ws', 'wss') else tcp_maker(proto, ip, port)
    return Connect(soc, (ip, port), lambda *_, **__: False)


def ws_maker(proto, ip, port) -> WSClientAdapter:
    try:
        ws = websocket.create_connection(
            '{}://{}:{}/'.format(proto, ip, port),
            sockopt=((socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),),
            class_=WSClientAdapter,
            enable_multithread=False,
            timeout=10,
        )
    except ALL_EXCEPTS as e:
        raise RuntimeError(e)
    ws.auth = True
    return ws


def tcp_maker(proto, ip, port) -> socket.socket:
    soc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    soc.settimeout(10)
    soc.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        soc.connect((ip, port))
    except ALL_EXCEPTS as e:
        raise RuntimeError(e)
    if proto == 'tls':
        try:
            # noinspection PyProtectedMember
            from websocket._http import _ssl_socket
            soc = _ssl_socket(soc, {}, ip)
        except ALL_EXCEPTS as e:
            raise RuntimeError(e)
    return soc
