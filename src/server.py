#!/usr/bin/env python3

import json
import os
import socket
import threading
import time
from io import BytesIO

import logger
from languages import SERVER as LNG
from owner import Owner
from utils import file_to_base64, base64_to_bytes, pretty_time

CRLF = b'\r\n'


class MDTServer(threading.Thread):
    # Канал для неблокирующих команд
    # Вызов: команда, данные
    NET = 'net'
    # Канал для блокирующих команд
    # Вызов: соманда, данные, блокировка, коннектор
    # Нужно вызывать блокировку, что бы сервер отлип и продолжил свою работу.
    NET_BLOCK = 'net_block'

    def __init__(self, cfg, log, owner: Owner):
        super().__init__(name='MDTServer')
        # Базовое, MajorDroid, API
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
        # API терминала для получения данных
        self.MTAPI = {
            'settings': self._api_settings,
            'volume': self._api_volume,
            'rec': self._api_rec,
            'pong': self._api_pong,
            'send_model': self._api_send_model,
        }
        # API терминала для двухстороннего обмена различными данными
        self.TRANSFER = {
            'recv_model': self._api_recv_model,
            'list_models': self._api_list_models,
            'ping': self._api_ping,
        }
        self._cfg = cfg
        self.log = log
        self.own = owner
        self.work = False
        self._socket = socket.socket()
        self._conn = Connect(None, None)
        self._lock = Unlock()

    def join(self, timeout=None):
        self.work = False
        self._conn.stop()
        self._lock()
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
                self._conn.insert(*self._socket.accept())
                self._conn.settimeout(5.0)
            except socket.timeout:
                continue
            allow = self._cfg.allow_connect(self._conn.ip)
            msg = '{} new connection from {}'.format('Allow' if allow else 'Ignore', self._conn.ip)
            self.log(msg, logger.DEBUG if allow else logger.WARN)
            try:
                if not allow:
                    continue
                for line in self._conn.read():
                    self._parse(line)
                try:
                    # Сообщаем серверу о завершении сеанса отпрвкой пустой команды
                    self._conn.write(b'')
                except RuntimeError:
                    pass
            finally:
                self._conn.close()
        self._socket.close()

    def _parse(self, data: str):
        if not data:
            return self.log(LNG['no_data'])
        else:
            self.log(LNG['get_data'].format(data[:1500]))

        cmd = data.split(':', 1)
        if len(cmd) != 2:
            cmd.append('')
        if self.own.has_subscribers(cmd[0], self.NET):
            self.log('Command {} intercepted'.format(repr(cmd[0])))
            self.own.sub_call(self.NET, cmd[0], cmd[1])
        elif self.own.has_subscribers(cmd[0], self.NET_BLOCK):
            self.log('Command {} intercepted in blocking mode'.format(repr(cmd[0])))
            self._lock.clear()
            self.own.sub_call(self.NET_BLOCK, cmd[0], cmd[1], self._lock, self._conn)
            # Приостанавливаем выполнение, ждем пока обработчик нас разблокирует
            # 1 минуты хватит?
            self._lock.wait(60)
        elif cmd[0] in self.MDAPI:
            self.MDAPI[cmd[0]](cmd[1])
        elif cmd[0] in self.MTAPI:
            try:
                self.MTAPI[cmd[0]](cmd[1])
            except RuntimeError as e:
                self.log(e, logger.ERROR)
        elif cmd[0] in self.TRANSFER:
            action = 'Transfer protocol ({})... '.format(cmd[0])
            try:
                self.TRANSFER[cmd[0]](cmd[0], cmd[1])
            except RuntimeError as e:
                self.log('{} ERROR: {}'.format(action, e), logger.ERROR)
            else:
                self.log('{} OK.'.format(action))
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
            raise RuntimeError(LNG['err_rec_param'].format(param))
        # a = param[0]  # rec, play или compile
        # b = param[1]  # 1-6
        # c = param[2]  # 1-3
        if param[0] in ('play', 'rec', 'compile', 'del', 'update', 'rollback'):
            self.own.terminal_call(param[0], param[1:])
        elif param[0] == 'save':
            self.own.die_in(3, True)
        else:
            raise RuntimeError(LNG['unknown_rec_cmd'].format(param[0]))

    def _api_send_model(self, data):
        """
        Получение модели от сервера.
        Нужно ли отправить на сервер результат? Пока не будем.
        Т.к. перезапись существующей модели может уронить сноубоя
        отпарсим данные и передадим их терминалу.

        Все данные распаковываются из json:
        code: если не 0, произошла ошибка, обязательно, число.
        filename: валидное имя файла модели, обязательно.
        msg: сообщение об ошибке, если это ошибка.
        body: файл модели завернутый в base64, обязательно если code 0
        phrase: ключевая фраза модели.
        username: пользователь модели.
        """
        try:
            data = json.loads(data)
            if not isinstance(data, dict):
                raise TypeError('Data must be dict type')
        except (json.decoder.JSONDecodeError, TypeError) as e:
            raise RuntimeError(e)
        # Проверяем ключи
        for key in ('filename', 'code'):
            if key not in data:
                raise RuntimeError('Missing key: {}'.format(repr(key)))
        # Ошибка?
        if data['code'] != 0:
            raise RuntimeError('Transfer error [{}]: {}'.format(data['code'], data.get('msg', '')))
        # Недопустимое имя модели?
        if not self._cfg.is_model_name(data['filename']):
            raise RuntimeError('Wrong model name: {}'.format(data['filename']))
        data['pmdl_name'] = data['filename']
        del data['filename']
        # И значения на корректность
        for key in ('username', 'phrase'):
            if key in data and not isinstance(data[key], str):
                raise RuntimeError('Wrong value type in {}: {}'.format(repr(key), repr(type(data[key]))))

        if 'body' not in data:
            raise RuntimeError('Missing key: body')
        # Переводим файл в байты, будем считать что файл не может быть меньше 3 кбайт
        data['body'] = base64_to_bytes(data['body'])
        if len(data['body']) < 1024 * 3:
            raise RuntimeError('File too small: {}'.format(len(data['body'])))
        self.own.terminal_call('send_model', data, save_time=False)

    def _api_recv_model(self, cmd, pmdl_name):
        """
        Отправка модели на сервер.
        Все данные пакуются в json:
        cmd: команда на которую отвечаем (без параметра), обязательно.
        code: если не 0, произошла ошибка, обязательно, число.
        filename: валидное имя файла модели, обязательно.
        msg: сообщение об ошибке, если это ошибка.
        body: файл модели завернутый в base64, обязательно если code 0
        phrase: ключевая фраза модели, если есть.
        username: пользователь модели, если есть.
        """
        if not self._cfg.is_model_name(pmdl_name):
            msg = 'Wrong model name: {}'.format(pmdl_name)
            self._conn.raise_recv_err(cmd, 1, msg, pmdl_name)

        pmdl_path = os.path.join(self._cfg.path['models'], pmdl_name)
        if not os.path.isfile(pmdl_path):
            msg = 'File {} not found'.format(pmdl_name)
            self._conn.raise_recv_err(cmd, 2, msg, pmdl_name)

        try:
            body = file_to_base64(pmdl_path)
        except IOError as e:
            msg = 'IOError: {}'.format(e)
            self._conn.raise_recv_err(cmd, 3, msg, pmdl_name)
            return

        phrase = self._cfg.gt('models', pmdl_name)
        username = self._cfg.gt('persons', pmdl_name)

        data = {'cmd': cmd, 'filename': pmdl_name, 'code': 0, 'body': body}
        if phrase:
            data['phrase'] = phrase
        if username:
            data['username'] = username
        self._conn.write(data)

    def _api_list_models(self, cmd, _):
        """
        Отправка на сервер моделей которые есть у терминала.
        Все данные пакуются в json:
        cmd: команда на которую отвечаем (без параметра), обязательно.
        code: если не 0, произошла ошибка, обязательно, число.
        msg: сообщение об ошибке, если это ошибка.
        body: json-объект типа dict, содержит 2 списка:
        - models: список всех моделей которые есть, может быть пустым, обязательно если code 0.
        - allow: список моделей из [models] allow, может быть пустым, обязательно если code 0.
        """
        data = {
            'cmd': cmd,
            'code': 0,
            'body': {
                'models': self._cfg.get_all_models(),
                'allow': self._cfg.get_allow_models()
            }
        }
        self._conn.write(data)

    def _api_ping(self, _, data):
        """
        Пустая команды для поддержания и проверки соединения,
        на 'ping' терминал пришлет 'pong'. Если пинг с данными,
        то он вернет их (можно сохранить туда время).
        Также терминал будет ожидать pong в ответ на ping (отправка не реализована).
        """
        cmd = 'pong'
        if data:
            cmd = '{}:{}'.format(cmd, data)
        self._conn.write(cmd)

    def _api_pong(self, data):
        if data:
            # Считаем пинг
            try:
                data = float(data)
            except (ValueError, TypeError):
                data = None
            else:
                data = time.time() - data
            if data:
                self.log('ping {}'.format(pretty_time(data)), logger.INFO)


class Connect:
    CHUNK_SIZE = 1024 * 4

    def __init__(self, conn, ip_info, work=True):
        self._conn = conn
        self._ip_info = ip_info
        self._work = work

    def stop(self):
        self._work = False

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
        self._ip_info = ip_info

    def read(self):
        """
        Генератор,
        читает байты из сокета, разделяет их по \r\n и возвращает результаты в str,
        получение пустых данных(\r\n\r\n), любая ошибка сокета или завершение работы прерывает итерацию.
        Для совместимости: Если в данных вообще не было \r\n, сделаем вид что получили <data>\r\n\r\n.
        """
        if self._conn:
            return self._conn_reader()

    def write(self, data):
        """
        Преобразует dict -> json, str -> bytes, (nothing) -> bytes('') и отправляет байты в сокет.
        В конце автоматически добавляет \r\n.
        В любой непонятной ситуации кидает RuntimeError.
        """
        if self._conn:
            self._conn_sender(data)

    def raise_recv_err(self, cmd, code, msg, pmdl_name=None):
        data = {'cmd': cmd, 'code': code, 'msg': msg}
        if pmdl_name is not None:
            data['filename'] = pmdl_name
        self.write(data)
        raise RuntimeError(msg)

    def _conn_sender(self, data):
        if not data:
            data = b''
        elif isinstance(data, dict):
            try:
                data = json.dumps(data, ensure_ascii=False).encode()
            except TypeError as e:
                raise RuntimeError(e)
        elif isinstance(data, str):
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
                except (BrokenPipeError, socket.timeout, InterruptedError) as e:
                    raise RuntimeError(e)

    def _conn_reader(self):
        data = b''
        this_legacy = True
        while self._work:
            try:
                chunk = self._conn.recv(self.CHUNK_SIZE)
            except (BrokenPipeError, socket.timeout, ConnectionResetError, AttributeError):
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
                try:
                    yield line.decode()
                except UnicodeDecodeError:
                    pass
                del line
        if this_legacy and data and self._work:
            # Данные пришли без \r\n, обработаем их как есть
            try:
                yield data.decode()
            except UnicodeDecodeError:
                pass


class Unlock(threading.Event):
    def __call__(self, *args, **kwargs):
        self.set()
