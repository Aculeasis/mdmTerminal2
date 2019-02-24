import json
import os
import threading
import time

import logger
from languages import SERVER as LNG
from lib.socket_wrapper import Connect
from owner import Owner
from utils import file_to_base64, base64_to_bytes, pretty_time


class InternalError(Exception):
    pass


class SocketAPIHandler(threading.Thread):
    # Канал для неблокирующих команд
    # Вызов: команда, данные
    NET = 'net'
    # Канал для блокирующих команд
    # Вызов: соманда, данные, блокировка, коннектор
    # Обработчик будет приостановлен на 60 сек или до вызова блокировки подписчиком.
    NET_BLOCK = 'net_block'

    def __init__(self, cfg, log, owner: Owner, name, duplex_mode=False):
        super().__init__(name=name)
        # Базовое, MajorDroid, API
        self.MDAPI = {
            'hi': self._api_terminal_direct,
            'voice': self._api_terminal_direct,
            'home': self._api_no_implement,
            'url': self._api_no_implement,
            'play': self._api_play,
            'pause': self._api_pause,
            'tts': self._api_terminal_direct,
            'ask': self._api_terminal_direct,
            'rtsp': self._api_no_implement,
            'run': self._api_no_implement,
        }
        # API терминала для получения данных
        self.MTAPI = {
            'settings': self._api_settings,
            'volume': self._api_terminal_direct,
            'volume_q': self._api_terminal_direct,
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
        # Клиент получит ответ на все ошибки коммуникации
        self._duplex_mode = duplex_mode

        self.work = False
        self._conn = Connect(None, None, self.do_ws_allow)

        self._lock = Unlock()

    def join(self, timeout=None):
        if self.work:
            self.work = False
            self._conn.stop()
            # self._lock()
            self.log('stopping...')
            super().join(timeout)
            self.log('stop.', logger.INFO)

    def start(self):
        if not self.work:
            self.work = True
            super().start()
            self.log('start', logger.INFO)

    def do_ws_allow(self, ip, port, token):
        raise NotImplemented

    def run(self):
        raise NotImplemented

    def _parse(self, data: str):
        if not data:
            self._internal_error_reply(400, '400', 'no data')
            self.log(LNG['no_data'])
            return
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
            try:
                self.MDAPI[cmd[0]](cmd[0], cmd[1])
            except (RuntimeError, InternalError) as e:
                self.log('MDAPI: {}'.format(e), logger.ERROR)
                if isinstance(e, InternalError):
                    self._internal_error_reply(407, cmd[0], str(e))
        elif cmd[0] in self.MTAPI:
            try:
                self.MTAPI[cmd[0]](cmd[0], cmd[1])
            except (RuntimeError, InternalError) as e:
                self.log('MTAPI: {}'.format(e), logger.ERROR)
                if isinstance(e, InternalError):
                    self._internal_error_reply(406, cmd[0], str(e))
        elif cmd[0] in self.TRANSFER:
            action = 'Transfer protocol ({})...'.format(cmd[0])
            try:
                self.TRANSFER[cmd[0]](cmd[0], cmd[1])
            except (RuntimeError, InternalError) as e:
                self.log('{} ERROR: {}'.format(action, e), logger.ERROR)
                if isinstance(e, InternalError):
                    self._internal_error_reply(405, cmd[0], str(e))
            else:
                self.log('{} OK.'.format(action))
        else:
            msg = LNG['unknown_cmd'].format(cmd[0])
            self.log(msg, logger.WARN)
            self._internal_error_reply(404, cmd[0], msg)

    def _internal_error_reply(self, code: int, cmd: str, msg: str):
        if not self._duplex_mode:
            return
        try:
            self._conn.write({'cmd': cmd, 'code': code, 'msg': msg})
        except RuntimeError:
            pass

    def _api_no_implement(self, name: str, cmd: str):
        # home, url, rtsp, run
        raise InternalError(LNG['no_implement'].format(name, cmd))

    def _api_terminal_direct(self, name: str, cmd: str):
        # hi, voice, tts, ask, volume, volume_q
        if name == 'hi':
            name = 'voice'
        self.own.terminal_call(name, cmd)

    def _api_play(self, _, cmd: str):
        self.own.music_play(cmd)

    def _api_pause(self, __, _):
        self.own.music_pause()

    def _api_settings(self, _, cmd: str):
        self.own.settings_from_srv(cmd)

    def _api_rec(self, _, cmd: str):  # mark
        param = cmd.split('_')  # должно быть вида rec_1_1, play_2_1, compile_5_1
        if len(param) != 3 or sum([1 if len(x) else 0 for x in param]) != 3:
            raise InternalError(LNG['err_rec_param'].format(param))
        # a = param[0]  # rec, play или compile
        # b = param[1]  # 1-6
        # c = param[2]  # 1-3
        if param[0] in ('play', 'rec', 'compile', 'del'):
            self.own.terminal_call(param[0], param[1:])
        elif param[0] == 'save':
            self.own.die_in(3, True)
        elif param[0] == 'update':
            self.own.update()
        elif param[0] == 'rollback':
            self.own.manual_rollback()
        else:
            raise InternalError(LNG['unknown_rec_cmd'].format(param[0]))

    def _api_send_model(self, _, data: str):
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
            raise InternalError(e)
        # Проверяем ключи
        for key in ('filename', 'code'):
            if key not in data:
                raise InternalError('Missing key: {}'.format(repr(key)))
        # Ошибка?
        if not isinstance(data['code'], int) or data['code']:
            raise InternalError('Transfer error [{}]: {}'.format(data['code'], data.get('msg', '')))
        # Недопустимое имя модели?
        if not self._cfg.is_model_name(data['filename']):
            raise InternalError('Wrong model name: {}'.format(data['filename']))
        # И значения на корректность
        for key in ('username', 'phrase'):
            if key in data and not isinstance(data[key], str):
                raise InternalError('Wrong value type in {}: {}'.format(repr(key), repr(type(data[key]))))

        if 'body' not in data:
            raise InternalError('Missing key: body')
        # Переводим файл в байты, будем считать что файл не может быть меньше 3 кбайт
        data['body'] = base64_to_bytes(data['body'])
        if len(data['body']) < 1024 * 3:
            raise InternalError('File too small: {}'.format(len(data['body'])))
        data = (data.get(key, '') for key in ('filename', 'body', 'username', 'phrase'))
        self.own.terminal_call('send_model', data, save_time=False)

    def _api_recv_model(self, cmd: str, pmdl_name: str):
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

    def _api_list_models(self, name: str, _):
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
            'cmd': name,
            'code': 0,
            'body': {
                'models': self._cfg.get_all_models(),
                'allow': self._cfg.get_allow_models()
            }
        }
        self._conn.write(data)

    def _api_ping(self, _, data: str):
        """
        Пустая команды для поддержания и проверки соединения,
        на 'ping' терминал пришлет 'pong'. Если пинг с данными,
        то он вернет их (можно сохранить туда время).
        Также терминал будет ожидать pong в ответ на ping.
        """
        cmd = 'pong'
        if data:
            cmd = '{}:{}'.format(cmd, data)
        self._conn.write(cmd)

    def _api_pong(self, _, data: str):
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


class Unlock(threading.Event):
    def __call__(self, *args, **kwargs):
        self.set()