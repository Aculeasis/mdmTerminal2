import base64
import hashlib
import json
import os
import threading
import time

import logger
from languages import SERVER as LNG
from lib.socket_wrapper import Connect
from owner import Owner
from utils import file_to_base64, pretty_time


def upgrade_duplex(own: Owner, soc: Connect, msg=''):
    cmd = 'upgrade duplex'
    if own.has_subscribers(cmd, cmd):
        lock = Unlock()
        own.sub_call(cmd, cmd, msg, lock, soc)
        lock.wait(30)
    else:
        raise RuntimeError('No subscribers: {}'.format(cmd))


class BaseAPIException(Exception):
    RETURN = None

    def __init__(self, code: int=1, msg=None, **kwargs):
        # 0-9 код ошибки от команды
        code = code if 10 > code > -1 else 1
        # 4000 - ошибка API
        code += 4000
        msg = self.__class__.__name__ if msg is None else str(msg)

        self.data = {'code': code, 'cmd': '', 'msg': msg}
        self.data.update(kwargs)

    def up(self, **kwargs):
        self.data.update(kwargs)

    def cmd_code(self, code):
        # 10-990 код команды
        self.data['code'] += code * 10

    def __str__(self):
        return '{cmd} {code}: {msg}'.format(**self.data)


class InternalException(BaseAPIException):
    pass


class ReturnException(BaseAPIException):
    RETURN = True
    pass


class NoReturnException(BaseAPIException):
    RETURN = False
    pass


class API:
    REPLY = 'reply'

    def __init__(self, cfg, log, owner: Owner):
        self.API = {
            # Базовое, MajorDroid, API
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
            # API терминала для получения данных
            'settings': self._api_settings,
            'volume': self._api_terminal_direct,
            'volume_q': self._api_terminal_direct,
            'rec': self._api_rec,
            'pong': self._api_pong,
            'send_model': self._api_send_model,
            # API терминала для двухстороннего обмена различными данными
            'recv_model': self._api_recv_model,
            'list_models': self._api_list_models,
            'ping': self._api_ping,
            'info': self._api_info,
            self.REPLY: self._api_reply_check,
        }
        self.API_CODE = {name: index for index, name in enumerate(self.API.keys(), 1)}
        self.cfg = cfg
        self.log = log
        self.own = owner

    def add_api(self, name: str, call) -> bool:
        if name in self.API:
            return False
        self.API[name] = call
        self.API_CODE = {name: index for index, name in enumerate(self.API.keys(), 1)}
        return True

    @staticmethod
    def json_parser(data: str, cmd: str= '', body_keys: tuple=()) -> dict:
        check_keys = []
        if cmd:
            check_keys.append('cmd')
        if body_keys:
            check_keys.append('body')
        try:
            data = json.loads(data)
            if not isinstance(data, dict):
                raise TypeError('Data must be dict type')
        except (json.decoder.JSONDecodeError, TypeError) as e:
            raise InternalException(msg=e)

        if 'code' not in data:
            raise InternalException(2, msg='Missing key: code')
        if data['code']:
            cmd_ = repr(data.get('cmd', ''))[:100]
            code_ = repr(data['code'])[:10]
            msg_ = repr(data.get('msg', ''))[:1000]
            raise NoReturnException(code=0, msg='Received error to {}. {}: {} '.format(cmd_, code_, msg_))
        for key in check_keys:
            if key not in data:
                raise InternalException(2, msg='Missing key: {}'.format(key))
        if cmd:
            if 'cmd' != data['cmd']:
                raise InternalException(3, 'Wrong value in cmd: {} != {}'.format(data['cmd'], cmd))
        if body_keys:
            if not isinstance(data['body'], dict):
                raise InternalException(4, 'body must be dict type, not \'{}\''.format(type(data['body'])))
            for key in body_keys:
                if key not in data['body']:
                    raise InternalException(5, 'Missing key in body: {}'.format(key))
            return data['body']
        return data

    def _api_reply_check(self, name, data):
        data = self.json_parser(data)
        cmd = data.get('cmd')
        result = None
        for key in ('msg', 'body'):
            if key in data:
                result = repr(data[key])[:1500]
                break
        if result is None and cmd is None:
            return
        result = result or '\'Unknown\''
        cmd = repr(cmd)[:100] if cmd else '\'Unknown\''
        self.log('API.{} Received reply to {}: {}'.format(name, cmd, result), logger.INFO)

    def _api_no_implement(self, name: str, cmd: str):
        """NotImplemented"""
        # home, url, rtsp, run
        raise InternalException(msg=LNG['no_implement'].format(name, cmd))

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

    def _api_rec(self, _, cmd: str):
        param = cmd.split('_')  # должно быть вида rec_1_1, play_2_1, compile_5_1
        if len(param) != 3 or sum([1 if len(x) else 0 for x in param]) != 3:
            raise InternalException(mgs=LNG['err_rec_param'].format(param))
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
            raise InternalException(2, LNG['unknown_rec_cmd'].format(param[0]))

    def _api_send_model(self, _, data: str):
        """
        Получение модели от сервера.
        Нужно ли отправить на сервер результат? Пока не будем.
        Т.к. перезапись существующей модели может уронить сноубоя
        отпарсим данные и передадим их терминалу.

        Все данные распаковываются из json, где в body:
        filename: валидное имя файла модели, обязательно.
        data: файл модели завернутый в base64, обязательно если code 0
        phrase: ключевая фраза модели.
        username: пользователь модели.
        """
        data = self.json_parser(data, body_keys=('filename', 'data'))
        # Недопустимое имя модели?
        if not self.cfg.is_model_name(data['filename']):
            raise InternalException(6, 'Wrong model name: {}'.format(data['filename']))
        # И значения на корректность
        for key in ('username', 'phrase'):
            if key in data and not isinstance(data[key], str):
                raise InternalException(3, 'Wrong value type in {}: {}'.format(repr(key), repr(type(data[key]))))

        # Переводим файл в байты, будем считать что файл не может быть меньше 3 кбайт
        try:
            data['data'] = base64.b64decode(data['data'])
        except (ValueError, TypeError) as e:
            raise InternalException(7, 'Invalid file data: {}'.format(e))
        if len(data['data']) < 1024 * 3:
            raise InternalException(8, 'File too small: {}'.format(len(data['data'])))
        data = (data.get(key, '') for key in ('filename', 'data', 'username', 'phrase'))
        self.own.terminal_call('send_model', data, save_time=False)

    def _api_recv_model(self, _, pmdl_name: str):
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
        if not self.cfg.is_model_name(pmdl_name):
            raise ReturnException(msg='Wrong model name: {}'.format(pmdl_name), filename=pmdl_name)

        pmdl_path = os.path.join(self.cfg.path['models'], pmdl_name)
        if not os.path.isfile(pmdl_path):
            raise ReturnException(2, 'File {} not found'.format(pmdl_name), filename=pmdl_name)

        try:
            data = file_to_base64(pmdl_path)
        except IOError as e:
            raise ReturnException(3, 'IOError: {}'.format(e), filename=pmdl_name)

        phrase = self.cfg.gt('models', pmdl_name)
        username = self.cfg.gt('persons', pmdl_name)

        body = {'filename': pmdl_name, 'data': data}
        if phrase:
            body['phrase'] = phrase
        if username:
            body['username'] = username
        return {'body': body}

    def _api_list_models(self, *_):
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
        return {'body': {'models': self.cfg.get_all_models(), 'allow': self.cfg.get_allow_models()}}

    @staticmethod
    def _api_ping(_, data: str):
        """
        Пустая команды для поддержания и проверки соединения,
        на 'ping' терминал пришлет 'pong'. Если пинг с данными,
        то он вернет их (можно сохранить туда время).
        Также терминал будет ожидать pong в ответ на ping.
        """
        cmd = 'pong'
        return '{}:{}'.format(cmd, data) if data else cmd

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

    def _api_info(self, _, cmd: str) -> dict:
        """
        Возвращает справку по команде из __doc__ или список доступных команд если команда не задана.
        Учитывает только команды представленные в API, подписчики не проверяются.
        """
        result = {'body': {'cmd': cmd}}
        if not cmd:
            result['body'].update(cmd=[x for x in self.API], msg='Available commands')
        elif cmd not in self.API:
            raise ReturnException(msg='Unknown command: {}'.format(cmd))
        else:
            if self.API[cmd].__doc__:
                clear_doc = self.API[cmd].__doc__.split('\n\n')[0].rstrip().strip('\n')
            else:
                clear_doc = 'Undocumented'
            result['body']['msg'] = clear_doc
        return result


class SocketAPIHandler(threading.Thread, API):
    # Канал для неблокирующих команд
    # Вызов: команда, данные
    NET = 'net'
    # Канал для блокирующих команд
    # Вызов: соманда, данные, блокировка, коннектор
    # Обработчик будет приостановлен на 60 сек или до вызова блокировки подписчиком.
    NET_BLOCK = 'net_block'

    def __init__(self, cfg, log, owner: Owner, name, duplex_mode=False):
        threading.Thread.__init__(self, name=name)
        API.__init__(self, cfg, log, owner)

        # Клиент получит ответ на все ошибки коммуникации
        self._duplex_mode = duplex_mode
        self.work = False
        self._conn = Connect(None, None, self.do_ws_allow)
        self._lock = Unlock()
        # Команды API не требующие авторизации
        self.NON_AUTH = {
            'authorization', 'hi', 'voice', 'play', 'pause', 'tts', 'ask', 'settings', 'volume', 'volume_q', 'rec',
            'remote_log', self.REPLY,
        }
        self.add_api('authorization', self._authorization)
        self.add_api('deauthorization', self._deauthorization)

    def _authorization(self, cmd, remote_hash):
        if not self._conn.auth:
            token = self.cfg.gt('smarthome', 'token')
            if token:
                local_hash = hashlib.sha3_512(token.encode()).hexdigest()
                if local_hash != remote_hash:
                    raise ReturnException(msg='forbidden: wrong hash')
            self._conn.auth = True
            msg = 'authorized'
            self.log('API.{} {}'.format(cmd, msg), logger.INFO)
            return {'msg': msg}
        return {'msg': 'already'}

    def _deauthorization(self, cmd, _):
        if self._conn.auth:
            self._conn.auth = False
            msg = 'deauthorized'
            self.log('API.{} {}'.format(cmd, msg), logger.INFO)
            return {'msg': msg}
        return {'msg': 'already'}

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

    def _call_api(self, cmd: str, data: str):
        try:
            result = self.API[cmd](cmd, data)
        except RuntimeError as e:
            self.log('Error {}: {}'.format(cmd, e), logger.ERROR)
        except BaseAPIException as e:
            self._handle_exception(cmd, e)
        else:
            if result:
                if isinstance(result, dict):
                    result.update({'cmd': cmd, 'code': 0})
                self._write(result)

    def _handle_exception(self, cmd: str, e: BaseAPIException, code=0):
        e.up(cmd=cmd)
        e.cmd_code(code or self.API_CODE.get(cmd, 1000))
        self.log('API.{}'.format(e), logger.WARN)
        return_ = e.RETURN if e.RETURN is not None else self._duplex_mode
        if return_:
            self._write(e.data)

    def parse(self, data: str):
        if not data:
            self._internal_error_reply(5001, '', 'no data')
            self.log(LNG['no_data'])
            return
        else:
            self.log(LNG['get_data'].format(data[:1500]))

        if data.startswith('{') and data.endswith('}'):
            cmd = (self.REPLY, data)
        else:
            cmd = data.split(':', 1)
            if len(cmd) != 2:
                cmd.append('')

        if not self._conn.auth and cmd[0] not in self.NON_AUTH:
            self._handle_exception(
                cmd[0],
                ReturnException(code=0, msg='forbidden: authorization is necessary'),
                self.API_CODE.get('authorization', 1000)
            )
        elif self.own.has_subscribers(cmd[0], self.NET):
            self.log('Command {} intercepted'.format(repr(cmd[0])))
            self.own.sub_call(self.NET, cmd[0], cmd[1])
        elif self.own.has_subscribers(cmd[0], self.NET_BLOCK):
            self.log('Command {} intercepted in blocking mode'.format(repr(cmd[0])))
            self._lock.clear()
            self.own.sub_call(self.NET_BLOCK, cmd[0], cmd[1], self._lock, self._conn)
            # Приостанавливаем выполнение, ждем пока обработчик нас разблокирует
            # 1 минуты хватит?
            self._lock.wait(60)
        elif cmd[0] in self.API:
            self._call_api(*cmd)
        else:
            msg = LNG['unknown_cmd'].format(cmd[0])
            self.log(msg, logger.WARN)
            self._internal_error_reply(5002, cmd[0], msg)

    def _write(self, data, quite=False):
        try:
            self._conn.write(data)
        except RuntimeError as e:
            self._conn.close()
            if not quite:
                self.log('Write error: {}'.format(e), logger.ERROR)

    def _internal_error_reply(self, code: int, cmd: str, msg: str):
        if self._duplex_mode:
            self._write({'cmd': cmd, 'code': code, 'msg': msg}, True)


class Unlock(threading.Event):
    def __call__(self, *args, **kwargs):
        self.set()
