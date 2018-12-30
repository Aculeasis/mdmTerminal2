#!/usr/bin/env python3

import socket
import threading

from SimpleWebSocketServer import WebSocket, SimpleWebSocketServer

from utils import Connect
import logger


class WSClient(WebSocket):
    def __init__(self, server, sock, address):
        self._proxy = None
        super().__init__(server, sock, address)
        if not self._is_allow():
            self.handleClose()
            return
        try:
            self._proxy = TCPProxy(self, server.remote)
        except RuntimeError as e:
            self.server.log('Proxy error: {}'.format(e))
            self.close()

    def _is_allow(self) -> bool:
        allow = self.server.allow is None or self.server.allow(self.address[0])
        msg = 'WSProxy {} new connection from {}'.format('allow' if allow else 'ignore', self.address[0])
        self.server.log(msg, logger.DEBUG if allow else logger.WARN)
        return allow

    def handleMessage(self):
        if self._proxy:
            self._proxy.send(self.data)

    def handleClose(self):
        self.close()
        if self._proxy:
            self._proxy.join()


class TCPProxy(threading.Thread):
    def __init__(self, client: WSClient, remote):
        super().__init__()
        self._client = client
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.settimeout(2)
        try:
            conn.connect(remote)
        except (BrokenPipeError, ConnectionResetError, ConnectionRefusedError, OSError, socket.timeout) as e:
            raise RuntimeError(e)
        self._conn = Connect(conn, remote)
        self._conn.r_wait()
        self._work = True
        self.start()

    def send(self, msg: str):
        if isinstance(msg, str):
            try:
                self._conn.write(msg)
            except RuntimeError:
                self.join()

    def join(self, timeout=None):
        if self._work:
            self._work = False
            self._conn.stop()
            super().join(timeout)

    def run(self):
        while self._work:
            for line in self._conn.read():
                self._client.sendMessage(line)
            self._conn.close()
            self._client.close()


class WSServer(SimpleWebSocketServer):
    def __init__(self, local, remote, allow, log):
        if local == remote:
            raise RuntimeError('Remote and local must be different: {}'.format(local))
        self.remote = remote
        self.allow = allow
        self.log = log
        super().__init__(*local, WSClient)


class Server(threading.Thread):
    def __init__(self, local=('', 8999), remote=('192.168.1.198', 7999), allow=None, log=print):
        super().__init__()
        self._data = (local, remote, allow, log)
        self._log = log
        self._server = None
        self._work = False

    def start(self):
        if not self._work:
            try:
                self._server = WSServer(*self._data)
            except (OSError, RuntimeError) as e:
                self._log(e, logger.ERROR)
            else:
                self._work = True
                super().start()
                self._log('start.', logger.INFO)

    def run(self):
        if self._work:
            try:
                self._server.serveforever()
            except ValueError:
                pass

    def join(self, timeout=None):
        if self._work:
            self._work = False
            self._log('stopping...')
            self._server.close()
            super().join()
            self._log('stop.', logger.INFO)


# def main():
#     import signal
#     lock = threading.Event()
#     signal.signal(signal.SIGINT, lambda *args, **kwargs: lock.set())
#     server = Server()
#     try:
#         server.start()
#     except RuntimeError as e:
#         print(e)
#     else:
#         lock.wait()
#         server.join()
#
#
# if __name__ == '__main__':
#     main()
