#!/usr/bin/env python3
"""
The MIT License (MIT)
Copyright (c) 2013 Dave P. https://github.com/dpallot/simple-websocket-server

This code was modified by Aculeasis, 2019
"""

import base64
import codecs
import errno
import hashlib
import json
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler
from io import BytesIO

import logger

_VALID_STATUS_CODES = [1000, 1001, 1002, 1003, 1007, 1008, 1009, 1010, 1011, 3000, 3999, 4000, 4999]

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


STREAM = 0x0
TEXT = 0x1
BINARY = 0x2
CLOSE = 0x8
PING = 0x9
PONG = 0xA

HEADERB1 = 1
HEADERB2 = 3
LENGTHSHORT = 4
LENGTHLONG = 5
MASK = 6
PAYLOAD = 7

MAXHEADER = 65536
MAXPAYLOAD = 33554432


CRLF = b'\r\n'
WS_MARK = b'GET '
AUTH_FAILED = logger.colored('Terminal rejected connection (incorrect ws_token?)', logger.COLORS[logger.ERROR])
AUTH_FAILED = '{}. {}!'.format(AUTH_FAILED, logger.colored('BYE', logger.COLORS[logger.CRIT]))


class Connect:
    CHUNK_SIZE = 1024 * 4

    def __init__(self, conn, ip_info, ws_allow, work=True):
        self._conn = conn
        self._is_ws = isinstance(conn, WebSocket)
        self._ip_info = ip_info
        self._ws_allow = ws_allow
        self._work = work
        self._r_wait = False

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
                    self._conn.close()
                except RuntimeError:
                    pass
                self._conn.client.close()
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
        self._is_ws = isinstance(conn, WebSocket)
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

    def raise_recv_err(self, cmd, code, msg, pmdl_name=None):
        data = {'cmd': cmd, 'code': code, 'msg': msg}
        if pmdl_name is not None:
            data['filename'] = pmdl_name
        self.write(data)
        raise RuntimeError(msg)

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
            return self._ws_sender(data)

        if isinstance(data, str):
            data = data.encode()
        elif not isinstance(data, bytes):
            raise RuntimeError('Unsupported data type: {}'.format(repr(type(data))))

        with BytesIO(data) as fp:
            del data
            chunk = True
            while chunk:
                chunk = fp.read(self.CHUNK_SIZE)
                try:
                    self._conn.send(chunk or CRLF)
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
                    self.insert(WebSocket(self._conn, CRLF.join((line, data)), self.CHUNK_SIZE), self._ip_info)
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
                self._conn.write(data)
            except AttributeError as e:
                raise RuntimeError(e)

    def _ws_reader(self):
        while self._work:
            try:
                for chunk in self._conn.read():
                    if not self._conn.auth:
                        if self._ws_allow(self.ip, self.port, chunk):
                            self._conn.auth = True
                            continue
                        try:
                            self._conn.write(AUTH_FAILED)
                        except RuntimeError:
                            pass
                        self.close()
                        return
                    yield chunk
            except socket.timeout:
                if self._r_wait:
                    continue
                else:
                    break
            except (RuntimeError, AttributeError, socket.error):
                break


class WebSocketCap(threading.Thread):
    def __init__(self, ws):
        super().__init__()
        self._ws = ws
        try:
            self._ws.settimeout(0.0)
        except socket.error:
            pass
        else:
            self.start()

    def run(self):
        while not self._ws.closed:
            time.sleep(0.3)
            try:
                for _ in self._ws.read(128):
                    pass
            except RuntimeError:
                break
            except socket.error as e:
                if e.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                    try:
                        self._ws.close()
                    except (RuntimeError, socket.error):
                        pass
                    break


class HTTPRequest(BaseHTTPRequestHandler):
    # noinspection PyMissingConstructor
    def __init__(self, request_text):
        self.rfile = BytesIO(request_text)
        self.raw_requestline = self.rfile.readline()
        self.error_code = self.error_message = None
        self.parse_request()


class WebSocket:
    def __init__(self, conn, init=b'', chunk_size=1024*4):
        self.client = conn
        self._init_data = init
        self.chunk_size = chunk_size

        self.auth = False
        self.poll = None

        self.handshaked = False
        self.headerbuffer = bytearray()

        self.fin = 0
        self.data = bytearray()
        self.opcode = 0
        self.hasmask = 0
        self.maskarray = None
        self.length = 0
        self.lengtharray = None
        self.index = 0
        self.request = None
        self.usingssl = False

        self.frag_start = False
        self.frag_type = BINARY
        self.frag_buffer = None
        self.frag_decoder = codecs.getincrementaldecoder('utf-8')(errors='strict')
        self.closed = False

        self.state = HEADERB1

        # restrict the size of header and payload for security reasons
        self.maxheader = MAXHEADER
        self.maxpayload = MAXPAYLOAD

    def settimeout(self, timeout):
        self.client.settimeout(timeout)

    def recv(self, *_):
        raise RuntimeError('Web socket is not socket')

    def send(self, *_):
        raise RuntimeError('Web socket is not socket')

    def _handle_packet(self):
        if self.opcode == CLOSE:
            pass
        elif self.opcode == STREAM:
            pass
        elif self.opcode == TEXT:
            pass
        elif self.opcode == BINARY:
            pass
        elif self.opcode == PONG or self.opcode == PING:
            if len(self.data) > 125:
                raise RuntimeError('control frame length can not be > 125')
        else:
            # unknown or reserved opcode so just close
            raise RuntimeError('unknown opcode')

        if self.opcode == CLOSE:
            status = 1000
            reason = u''
            length = len(self.data)

            if length == 0:
                pass
            elif length >= 2:
                status = struct.unpack_from('!H', self.data[:2])[0]
                reason = self.data[2:]

                if status not in _VALID_STATUS_CODES:
                    status = 1002

                if len(reason) > 0:
                    try:
                        reason = reason.decode('utf8', errors='strict')
                    except UnicodeDecodeError:
                        status = 1002
            else:
                status = 1002

            self.close(status, reason)
            return

        elif self.fin == 0:
            if self.opcode != STREAM:
                if self.opcode == PING or self.opcode == PONG:
                    raise RuntimeError('control messages can not be fragmented')

                self.frag_type = self.opcode
                self.frag_start = True
                self.frag_decoder.reset()

                if self.frag_type == TEXT:
                    self.frag_buffer = []
                    utf_str = self.frag_decoder.decode(self.data, final=False)
                    if utf_str:
                        self.frag_buffer.append(utf_str)
                else:
                    self.frag_buffer = bytearray()
                    self.frag_buffer.extend(self.data)

            else:
                if self.frag_start is False:
                    raise RuntimeError('fragmentation protocol error')

                if self.frag_type == TEXT:
                    utf_str = self.frag_decoder.decode(self.data, final=False)
                    if utf_str:
                        self.frag_buffer.append(utf_str)
                else:
                    self.frag_buffer.extend(self.data)

        else:
            if self.opcode == STREAM:
                if self.frag_start is False:
                    raise RuntimeError('fragmentation protocol error')

                if self.frag_type == TEXT:
                    utf_str = self.frag_decoder.decode(self.data, final=True)
                    self.frag_buffer.append(utf_str)
                    self.data = ''.join(self.frag_buffer)
                else:
                    self.frag_buffer.extend(self.data)
                    self.data = self.frag_buffer

                self.frag_decoder.reset()
                self.frag_type = BINARY
                self.frag_start = False
                self.frag_buffer = None
                return self.data
            elif self.opcode == PING:
                self._send_message(False, PONG, self.data)

            elif self.opcode == PONG:
                pass

            else:
                if self.frag_start is True:
                    raise RuntimeError('fragmentation protocol error')

                if self.opcode == TEXT:
                    try:
                        self.data = self.data.decode('utf8', errors='strict')
                    except Exception as e:
                        raise RuntimeError('invalid utf-8 payload: {}'.format(e))

                return self.data

    def read(self, chunk=0):
        # yielding result
        if self.closed:
            raise RuntimeError('Already closed')

        # do the HTTP header and handshake
        if not self.handshaked:
            if self._init_data:
                data, self._init_data = self._init_data, None
                timeout = self.client.gettimeout()
                self.client.settimeout(0.0)
                try:
                    data += self.client.recv(self.chunk_size)
                except socket.error:
                    pass
                finally:
                    self.client.settimeout(timeout)
            else:
                data = self.client.recv(self.chunk_size)

            if not data:
                raise RuntimeError('remote socket closed')
            # accumulate
            self.headerbuffer.extend(data)

            if len(self.headerbuffer) >= self.maxheader:
                raise RuntimeError('header exceeded allowable size')

            # indicates end of HTTP header
            if b'\r\n\r\n' in self.headerbuffer:
                self.request = HTTPRequest(self.headerbuffer)

                # handshake rfc 6455
                try:
                    key = self.request.headers['Sec-WebSocket-Key']
                    k = key.encode('ascii') + GUID_STR.encode('ascii')
                    k_s = base64.b64encode(hashlib.sha1(k).digest()).decode('ascii')
                    h_str = HANDSHAKE_STR.format(acceptstr=k_s).encode('ascii')
                    self._send_buffer(h_str)
                    self.handshaked = True
                except Exception as e:
                    try:
                        self._send_buffer(FAILED_HANDSHAKE_STR.encode('ascii'))
                    except RuntimeError:
                        pass
                    self.client.close()
                    raise RuntimeError('handshake failed: {}'.format(e))

        # else do normal data
        else:
            data = self.client.recv(chunk or self.chunk_size)
            if not data:
                raise RuntimeError("remote socket closed")

            for d in data:
                for result in self._parse_message(d):
                    if result is not None:
                        yield result

    def close(self, status=1000, reason=''):
        try:
            if not self.closed:
                close_msg = bytearray()
                close_msg.extend(struct.pack("!H", status))
                if isinstance(reason, str):
                    close_msg.extend(reason.encode())
                else:
                    close_msg.extend(reason)

                self._send_message(False, CLOSE, close_msg)
        finally:
            self.closed = True

    def _send_buffer(self, buff):
        if self.closed:
            raise RuntimeError('Already closed')
        tosend = len(buff)
        already_sent = 0
        while tosend > 0:
            try:
                # i should be able to send a bytearray
                sent = self.client.send(buff[already_sent:])
                if not sent:
                    raise RuntimeError('socket connection broken')

                already_sent += sent
                tosend -= sent

            except socket.error as e:
                # if we have full buffers then wait for them to drain and try again
                if e.errno in [errno.EAGAIN, errno.EWOULDBLOCK]:
                    continue
                else:
                    raise RuntimeError(e)

    def write(self, data):
        """
        Send websocket data frame to the client.

        If data is a unicode object then the frame is sent as Text.
        If the data is a bytearray object then the frame is sent as Binary.
        """
        opcode = BINARY
        if isinstance(data, str):
            opcode = TEXT
        self._send_message(False, opcode, data)

    def _send_message(self, fin, opcode, data):
        payload = bytearray()

        b1 = 0
        b2 = 0
        if not fin:
            b1 |= 0x80
        b1 |= opcode

        if isinstance(data, str):
            data = data.encode()

        length = len(data)
        payload.append(b1)

        if length <= 125:
            b2 |= length
            payload.append(b2)

        elif 126 <= length <= 65535:
            b2 |= 126
            payload.append(b2)
            payload.extend(struct.pack("!H", length))

        else:
            b2 |= 127
            payload.append(b2)
            payload.extend(struct.pack("!Q", length))

        if length:
            payload.extend(data)

        self._send_buffer(payload)

    def _parse_message(self, byte):
        # read in the header
        if self.state == HEADERB1:

            self.fin = byte & 0x80
            self.opcode = byte & 0x0F
            self.state = HEADERB2

            self.index = 0
            self.length = 0
            self.lengtharray = bytearray()
            self.data = bytearray()

            if byte & 0x70:
                raise RuntimeError('RSV bit must be 0')

        elif self.state == HEADERB2:
            mask = byte & 0x80
            length = byte & 0x7F

            if self.opcode == PING and length > 125:
                raise RuntimeError('ping packet is too large')

            if mask == 128:
                self.hasmask = True
            else:
                self.hasmask = False

            if length <= 125:
                self.length = length

                # if we have a mask we must read it
                if self.hasmask is True:
                    self.maskarray = bytearray()
                    self.state = MASK
                else:
                    # if there is no mask and no payload we are done
                    if self.length <= 0:
                        try:
                            yield self._handle_packet()
                        finally:
                            self.state = HEADERB1
                            self.data = bytearray()

                    # we have no mask and some payload
                    else:
                        # self.index = 0
                        self.data = bytearray()
                        self.state = PAYLOAD

            elif length == 126:
                self.lengtharray = bytearray()
                self.state = LENGTHSHORT

            elif length == 127:
                self.lengtharray = bytearray()
                self.state = LENGTHLONG

        elif self.state == LENGTHSHORT:
            self.lengtharray.append(byte)

            if len(self.lengtharray) > 2:
                raise RuntimeError('short length exceeded allowable size')

            if len(self.lengtharray) == 2:
                self.length = struct.unpack_from('!H', self.lengtharray)[0]

                if self.hasmask:
                    self.maskarray = bytearray()
                    self.state = MASK
                else:
                    # if there is no mask and no payload we are done
                    if self.length <= 0:
                        try:
                            yield self._handle_packet()
                        finally:
                            self.state = HEADERB1
                            self.data = bytearray()

                    # we have no mask and some payload
                    else:
                        self.data = bytearray()
                        self.state = PAYLOAD

        elif self.state == LENGTHLONG:

            self.lengtharray.append(byte)

            if len(self.lengtharray) > 8:
                raise RuntimeError('long length exceeded allowable size')

            if len(self.lengtharray) == 8:
                self.length = struct.unpack_from('!Q', self.lengtharray)[0]

                if self.hasmask is True:
                    self.maskarray = bytearray()
                    self.state = MASK
                else:
                    # if there is no mask and no payload we are done
                    if self.length <= 0:
                        try:
                            yield self._handle_packet()
                        finally:
                            self.state = HEADERB1
                            self.data = bytearray()

                    # we have no mask and some payload
                    else:
                        # self.index = 0
                        self.data = bytearray()
                        self.state = PAYLOAD

        # MASK STATE
        elif self.state == MASK:
            self.maskarray.append(byte)

            if len(self.maskarray) > 4:
                raise RuntimeError('mask exceeded allowable size')

            if len(self.maskarray) == 4:
                # if there is no mask and no payload we are done
                if self.length <= 0:
                    try:
                        yield self._handle_packet()
                    finally:
                        self.state = HEADERB1
                        self.data = bytearray()

                # we have no mask and some payload
                else:
                    # self.index = 0
                    self.data = bytearray()
                    self.state = PAYLOAD

        # PAYLOAD STATE
        elif self.state == PAYLOAD:
            if self.hasmask is True:
                self.data.append(byte ^ self.maskarray[self.index % 4])
            else:
                self.data.append(byte)

            # if length exceeds allowable size then we except and remove the connection
            if len(self.data) >= self.maxpayload:
                raise RuntimeError('payload exceeded allowable size')

            # check if we have processed length bytes; if so we are done
            if (self.index+1) == self.length:
                try:
                    yield self._handle_packet()
                finally:
                    # self.index = 0
                    self.state = HEADERB1
                    self.data = bytearray()
            else:
                self.index += 1
