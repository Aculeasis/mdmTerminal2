#!/usr/bin/env python3
"""
The MIT License (MIT)
Copyright (c) 2013 Dave P. https://github.com/dpallot/simple-websocket-server

This code was modified by Aculeasis, 2019
"""

import base64
import hashlib
import http.client
import json
import socket
import ssl
import threading
import time
from io import BytesIO

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

GUID_STR = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


CRLF = b'\r\n'
WS_MARK = b'GET '
AUTH_FAILED = 'Terminal rejected connection (incorrect ws_token?). BYE!'
ALL_EXCEPTS = (ConnectionError, OSError, websocket.WebSocketException, TypeError, ValueError)


class Connect:
    CHUNK_SIZE = 1024 * 4

    def __init__(self, conn, ip_info, ws_allow, work=True):
        self._conn = conn
        self._is_ws = isinstance(conn, websocket.WebSocket)
        self._ip_info = ip_info
        self._ws_allow = ws_allow
        self._work = work
        self._r_wait = False
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

    def stop(self):
        self._work = False

    def r_wait(self):
        self._r_wait = True

    @property
    def ip(self):
        return self._ip_info[0] if self._ip_info else None

    @property
    def port(self):
        return self._ip_info[1] if self._ip_info else None

    def settimeout(self, timeout):
        if self._conn:
            self._conn.settimeout(timeout)

    def close(self):
        if self._conn:
            if self._is_ws:
                try:
                    self._conn.close(timeout=0.5)
                except AttributeError:
                    pass
            else:
                try:
                    # Сообщаем серверу о завершении сеанса отпрвкой CRLFCRLF
                    self._conn_sender(CRLF)
                except RuntimeError:
                    pass
                self._conn.close()

    def extract(self):
        if self._conn:
            try:
                return Connect(self._conn, self._ip_info, self._work)
            finally:
                self._conn = None
                self._ip_info = None

    def insert(self, conn, ip_info):
        self._conn = conn
        self._is_ws = isinstance(conn, websocket.WebSocket)
        self._ip_info = ip_info

    def read(self):
        """
        Генератор,
        читает байты из сокета, разделяет их по \r\n и возвращает результаты в str,
        получение пустых данных(\r\n\r\n), любая ошибка сокета или завершение работы прерывает итерацию.
        Для совместимости: Если в данных вообще не было \r\n, сделаем вид что получили <data>\r\n\r\n.
        При получении `GET ` первой командой превращает сокет в веб-сокет.
        """
        if self._conn:
            with self._recv_lock:
                return self._ws_reader() if self._is_ws else self._conn_reader()

    def write(self, data):
        """
        Преобразует dict -> json, str -> bytes, (nothing) -> bytes('') и отправляет байты в сокет.
        В конце автоматически добавляет \r\n.
        Если это веб-сокет то кидаем все в str.
        В любой непонятной ситуации кидает RuntimeError.
        """
        if self._conn:
            self._conn_sender(data)

    def start_remote_log(self):
        """
        Нельзя просто так взять и закрыть веб-сокет.
        """
        if self._is_ws and self._conn.poll is None:
            self._conn.poll = WebSocketCap(self._conn)

    def _conn_sender(self, data):
        if not data:
            data = ''
        elif isinstance(data, dict):
            try:
                data = json.dumps(data, ensure_ascii=False)
            except TypeError as e:
                raise RuntimeError(e)

        if self._is_ws:
            if isinstance(data, bytes):
                data = data.decode()
            elif not isinstance(data, str):
                raise RuntimeError('Unsupported data type: {}'.format(repr(type(data))))
            with self._send_lock:
                return self._ws_sender(data)

        if isinstance(data, str):
            data = data.encode()
        elif not isinstance(data, bytes):
            raise RuntimeError('Unsupported data type: {}'.format(repr(type(data))))

        data += CRLF
        with self._send_lock:
            while data:
                sending = self._socket_send(data)
                data = data[sending:]

    def _socket_send(self, data: bytes) -> int:
        try:
            return self._conn.send(data)
        except (socket.error, AttributeError) as e:
            raise RuntimeError(e)

    def _conn_reader(self):
        data = b''
        this_legacy = True
        first_line = True
        while self._work:
            try:
                chunk = self._conn.recv(self.CHUNK_SIZE)
            except socket.timeout:
                if self._r_wait:
                    continue
                else:
                    break
            except (socket.error, RuntimeError, AttributeError):
                break
            if not chunk:
                # сокет закрыли, пустой объект
                break
            data += chunk
            while CRLF in data:
                # Обрабатываем все строки разделенные \r\n отдельно, пустая строка завершает сеанс
                this_legacy = False
                line, data = data.split(CRLF, 1)
                if not line:
                    return

                if first_line and line.startswith(WS_MARK):
                    # websocket
                    self.insert(WSServerAdapter(self._conn, data, self.CHUNK_SIZE), self._ip_info)
                    del line, data
                    for chunk in self._ws_reader():
                        yield chunk
                    return
                first_line = False

                try:
                    yield line.decode()
                except UnicodeDecodeError:
                    continue
                del line
        if this_legacy and data and self._work:
            # Данные пришли без \r\n, обработаем их как есть
            try:
                yield data.decode()
            except UnicodeDecodeError:
                pass

    def _ws_sender(self, data):
        if self._conn.auth:
            try:
                self._conn.send(data)
            except ALL_EXCEPTS as e:
                raise RuntimeError(e)

    def _ws_reader(self):
        while self._work:
            try:
                chunk = self._conn.recv()
                if chunk is None:
                    continue
                if not self._conn.auth:
                    if not self._ws_auth(chunk):
                        return
                    continue
                yield chunk
            except websocket.WebSocketTimeoutException:
                if self._r_wait:
                    continue
                else:
                    break
            except (websocket.WebSocketException, TypeError, ValueError, AttributeError):
                break

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
            except (websocket.WebSocketException, TypeError, ValueError, AttributeError):
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
    def __init__(self, conn, init=b'', chunk_size=1024*4):
        super().__init__()
        self.sock = conn
        self.connected = True
        with self.readlock, self.lock:
            timeout = self.sock.gettimeout()
            self.sock.settimeout(10)
            try:
                self._handshake(init, chunk_size)
            except Exception as e:
                self.shutdown()
                raise RuntimeError(e)
            self.sock.settimeout(timeout)

    def send_frame(self, frame):
        # A server must not mask any frames that it sends to the client.
        frame.mask = 0
        return super().send_frame(frame)

    def _handshake(self, init_data, chunk_size):
        def raw_send(msg):
            while msg:
                sending = self._send(msg)
                msg = msg[sending:]

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
                raise RuntimeError('remote socket closed')
            # accumulate
            header_buffer.extend(data)

            if len(header_buffer) >= max_header:
                raise RuntimeError('header exceeded allowable size')

            # indicates end of HTTP header
            if b'\r\n\r\n' in header_buffer:
                # handshake rfc 6455
                try:
                    key = http.client.parse_headers(BytesIO(header_buffer))['Sec-WebSocket-Key']
                    k = key.encode('ascii') + GUID_STR.encode('ascii')
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
