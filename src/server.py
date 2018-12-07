#!/usr/bin/env python3

import socket
import threading

import logger
from languages import SERVER as LNG
from owner import Owner


class MDTServer(threading.Thread):
    def __init__(self, cfg, log, owner: Owner):
        super().__init__(name='MDTServer')
        self.MDAPI = {
            'hi': self._api_voice,
            'voice': self._api_voice,
            'home': self._api_home,
            'url': self._api_url,
            'play': self._api_play,
            'pause': self._api_pause,
            'tts': self._api_tts,
            'ask': self._api_ask,
            'rtsp': self._api_rtsp,
            'run': self._api_run,
        }
        self.MTAPI = {
            'settings': self._api_settings,
            'volume': self._api_volume,
            'rec': self._api_rec,
        }

        self._cfg = cfg
        self.log = log
        self.own = owner
        self.work = False
        self._socket = socket.socket()

    def join(self, timeout=None):
        self.work = False
        self.log('stopping...')
        super().join(timeout)
        self.log('stop.', logger.INFO)

    def start(self):
        self.work = True
        super().start()
        self.log('start', logger.INFO)

    def _open_socket(self) -> bool:
        ip = ''
        port = 7999
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.settimeout(1)
        try:
            self._socket.bind((ip, port))
        except OSError as e:
            say = LNG['err_start_say'].format(LNG['err_already_use'] if e.errno == 98 else '')
            self.log(LNG['err_start'].format(ip, port, e), logger.CRIT)
            self.own.say(say)
            return False
        self._socket.listen(1)
        return True

    def run(self):
        if not self._open_socket():
            return
        while self.work:
            try:
                conn, ip_info = self._socket.accept()
                conn.settimeout(5.0)
            except socket.timeout:
                continue
            allow = self._cfg.allow_connect(ip_info[0])
            msg = '{} new connection from {}'.format('Allow' if allow else 'Ignore', ip_info[0])
            self.log(msg, logger.DEBUG if allow else logger.WARN)
            try:
                if allow:
                    self._parse(self._socket_reader(conn))
            finally:
                conn.close()
        self._socket.close()

    def _parse(self, data: str):
        if not data:
            return self.log(LNG['no_data'])
        else:
            self.log(LNG['get_data'].format(data))

        cmd = data.split(':', maxsplit=1)
        if len(cmd) != 2:
            cmd.append('')
        if cmd[0] in self.MDAPI:
            self.MDAPI[cmd[0]](cmd[1])
        elif cmd[0] in self.MTAPI:
            self.MTAPI[cmd[0]](cmd[1])
        else:
            self.log(LNG['unknown_cmd'].format(cmd[0]), logger.WARN)

    def _api_voice(self, cmd: str):
        self.own.terminal_call('voice', cmd)

    def _api_home(self, cmd: str):
        self.log(LNG['no_implement'].format('home', cmd), logger.WARN)

    def _api_url(self, cmd: str):
        self.log(LNG['no_implement'].format('url', cmd), logger.WARN)

    def _api_play(self, cmd: str):
        self.own.mpd_play(cmd)

    def _api_pause(self, _):
        self.own.mpd_pause()

    def _api_tts(self, cmd: str):
        self.own.terminal_call('tts', cmd)

    def _api_ask(self, cmd: str):
        self.own.terminal_call('ask', cmd)

    def _api_rtsp(self, cmd: str):
        self.log(LNG['no_implement'].format('rtsp', cmd), logger.WARN)

    def _api_run(self, cmd: str):
        self.log(LNG['no_implement'].format('run', cmd), logger.WARN)

    def _api_settings(self, cmd: str):
        self.own.settings_from_mjd(cmd)

    def _api_volume(self, cmd: str):
        self.own.terminal_call('volume', cmd)

    def _api_rec(self, cmd: str):
        param = cmd.split('_')  # должно быть вида rec_1_1, play_2_1, compile_5_1
        if len(param) != 3 or sum([1 if len(x) else 0 for x in param]) != 3:
            self.log(LNG['err_rec_param'].format(param), logger.ERROR)
            return
        # a = param[0]  # rec, play или compile
        # b = param[1]  # 1-6
        # c = param[2]  # 1-3
        if param[0] in ('play', 'rec', 'compile', 'del', 'update', 'rollback'):
            self.own.terminal_call(param[0], param[1:])
        elif param[0] == 'save':
            self.own.die_in(3, True)
        else:
            self.log(LNG['unknown_rec_cmd'].format(param[0]), logger.ERROR)

    @staticmethod
    def _socket_reader(conn) -> str:
        crlf = b'\r\n'
        data = b''
        while crlf not in data:  # ждём первую строку
            try:
                tmp = conn.recv(1024)
            except (BrokenPipeError, socket.timeout):
                break
            if not tmp:  # сокет закрыли, пустой объект
                break
            data += tmp
        return data.split(crlf, 1)[0].decode()
