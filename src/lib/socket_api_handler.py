import base64
import hashlib
import json
import os
import threading
import time

import logger
from lib.map_settings.map_settings import make_map_settings
from lib.socket_wrapper import Connect
from owner import Owner
from utils import file_to_base64, pretty_time


def api_commands(*commands):
    def wrapper(f):
        for command in commands:
            if not (isinstance(command, str) and command):
                raise RuntimeError('{} command must be a non empty string: {}'.format(f, command))
        f.api_commands = commands
        return f
    return wrapper


def upgrade_duplex(own: Owner, soc: Connect, msg=''):
    cmd = 'upgrade duplex'
    if own.has_subscribers(cmd, cmd):
        lock = Unlock()
        own.sub_call(cmd, cmd, msg, lock, soc)
        lock.wait(30)
    else:
        raise RuntimeError('No subscribers: {}'.format(cmd))


def json_parser(data: str, keys: tuple = ()) -> dict:
    try:
        data = json.loads(data)
        if not isinstance(data, dict):
            raise TypeError('Data must be dict type')
    except (json.decoder.JSONDecodeError, TypeError) as e:
        raise InternalException(msg=e)

    for key in keys:
        if key not in data:
            raise InternalException(5, 'Missing key: {}'.format(key))
    return data


class Null:
    def __repr__(self):
        return 'null'


class InternalException(Exception):
    def __init__(self, code: int = 1, msg=None, id_=None, method='method'):
        # 0-9 код ошибки от команды
        code = code if code < 10 else 1
        # 4000 - ошибка API
        if code > -1:
            code += 4000
        msg = self.__class__.__name__ if msg is None else str(msg)

        self.error = {'code': code, 'message': msg}
        self.id = id_
        self.method = method

    def cmd_code(self, code):
        # 10-990 код команды
        if self.error['code'] > -1:
            self.error['code'] += code * 10

    @property
    def data(self):
        return {'error': self.error, 'id': self.id if not isinstance(self.id, Null) else None}

    def __str__(self):
        return '{} {code}: {message}'.format(self.method, **self.error)


class API:
    def __init__(self, cfg, log, owner: Owner):
        self.API, self.API_CODE = {}, {}
        self._collector()
        self.cfg = cfg
        self.log = log
        self.own = owner

    def _collector(self):
        for attr in dir(self):
            if attr.startswith('__'):
                continue
            obj = getattr(self, attr)
            commands = getattr(obj, 'api_commands', None)
            if not (commands and isinstance(commands, tuple)):
                continue
            for command in commands:
                if command in self.API:
                    raise RuntimeError('command {} already linked to {}'.format(command, self.API[command]))
                self.API[command] = obj
        self.API_CODE = {name: index for index, name in enumerate(self.API.keys(), 1)}

    @api_commands('home', 'url', 'rts', 'run')
    def _api_no_implement(self, cmd: str, _):
        """NotImplemented"""
        raise InternalException(msg='Not implemented yet - {}'.format(cmd))

    @api_commands('hi', 'voice', 'tts', 'ask', 'volume', 'volume_q', 'music_volume', 'music_volume_q', 'listener')
    def _api_terminal_direct(self, name: str, cmd: str):
        if name == 'hi':
            name = 'voice'
        self.own.terminal_call(name, cmd)

    @api_commands('play')
    def _api_play(self, _, cmd: str):
        self.own.music_play(cmd)

    @api_commands('pause')
    def _api_pause(self, __, _):
        self.own.music_pause()

    @api_commands('settings')
    def _api_settings(self, _, cmd: str) -> dict:
        return self.own.settings_from_srv(cmd)

    @api_commands('rec')
    def _api_rec(self, _, cmd: str):
        param = cmd.split('_')  # должно быть вида rec_1_1, play_2_1, compile_5_1
        if len(param) != 3 or sum([1 if len(x) else 0 for x in param]) != 3:
            raise InternalException(msg='Error parsing parameters for \'rec\': {}'.format(repr(param)[:1500]))
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
            raise InternalException(2, 'Unknown command for \'rec\': {}'.format(repr(param[0])[:100]))

    @api_commands('send_model')
    def _api_send_model(self, _, data: str):
        """
        Получение модели от сервера.
        Нужно ли отправить на сервер результат? Пока не будем.
        Т.к. перезапись существующей модели может уронить сноубоя
        отпарсим данные и передадим их терминалу.

        Все данные распаковываются из json, где:
        filename: валидное имя файла модели, обязательно.
        data: файл модели завернутый в base64, обязательно.
        phrase: ключевая фраза модели.
        username: пользователь модели.
        """
        data = json_parser(data, keys=('filename', 'data'))
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

    @api_commands('recv_model')
    def _api_recv_model(self, _, pmdl_name: str):
        """
        Отправка модели на сервер.
        Все данные пакуются в json:
        filename: валидное имя файла модели, обязательно.
        data: файл модели завернутый в base64, обязательно если code 0
        phrase: ключевая фраза модели, если есть.
        username: пользователь модели, если есть.
        """
        if not self.cfg.is_model_name(pmdl_name):
            raise InternalException(msg='Wrong model name: {}'.format(pmdl_name))

        pmdl_path = os.path.join(self.cfg.path['models'], pmdl_name)
        if not os.path.isfile(pmdl_path):
            raise InternalException(2, 'File {} not found'.format(pmdl_name))

        try:
            result = {'filename': pmdl_name, 'data': file_to_base64(pmdl_path)}
        except IOError as e:
            raise InternalException(3, 'IOError: {}'.format(e))

        phrase = self.cfg.gt('models', pmdl_name)
        username = self.cfg.gt('persons', pmdl_name)

        if phrase:
            result['phrase'] = phrase
        if username:
            result['username'] = username
        return result

    @api_commands('list_models')
    def _api_list_models(self, *_):
        """
        Отправка на сервер моделей которые есть у терминала.
        Все данные пакуются в json:
        - models: список всех моделей которые есть, может быть пустым, обязательно если code 0.
        - allow: список моделей из [models] allow, может быть пустым, обязательно если code 0.
        """
        return {'models': self.cfg.get_all_models(), 'allow': self.cfg.get_allow_models()}

    @staticmethod
    @api_commands('ping')
    def _api_ping(_, data: str):
        """
        Пустая команды для поддержания и проверки соединения,
        вернет данные
        """
        return data

    @api_commands('pong')
    def _api_pong(self, _, data: str):
        if data:
            # Считаем пинг
            try:
                data = time.time() - float(data)
            except (ValueError, TypeError):
                pass
            else:
                self.log('ping {}'.format(pretty_time(data)), logger.INFO)

    @api_commands('info')
    def _api_info(self, _, cmd: str) -> dict:
        """
        Возвращает справку по команде из __doc__ или список доступных команд если команда не задана.
        Учитывает только команды представленные в API, подписчики не проверяются.
        """
        result = {'cmd': cmd}
        if not cmd:
            result.update(cmd=[x for x in self.API], msg='Available commands')
        elif cmd not in self.API:
            raise InternalException(msg='Unknown command: {}'.format(cmd))
        else:
            if self.API[cmd].__doc__:
                clear_doc = self.API[cmd].__doc__.split('\n\n')[0].rstrip().strip('\n')
            else:
                clear_doc = 'Undocumented'
            result['msg'] = clear_doc
        return result

    @api_commands('notifications.list')
    def _api_notifications_list(self, *_):
        return self.own.list_notifications()

    @api_commands('notifications.add', 'notifications.remove')
    def _api_notifications_modify(self, cmd: str, events: str):
        try:
            events = json.loads(events)
            if not isinstance(events, list):
                events = None
        except (json.decoder.JSONDecodeError, TypeError):
            if events:
                events = events.split(',')
        if not events:
            raise InternalException(msg='empty events list')
        if cmd.endswith('.remove'):
            return self.own.remove_notifications(events)
        elif cmd.endswith('.add'):
            return self.own.add_notifications(events)
        raise InternalException(code=2, msg='BOOM!')

    @api_commands('get_map_settings')
    def _api_get_map_settings(self, *_):
        return make_map_settings(self.cfg.wiki_desc)

    # @api_commands('call.plugin', 'call.owner', 'call.global')
    @api_commands('call.plugin')
    def _api_rpc_call(self, cmd: str, data: str):
        if not self.cfg.gt('smarthome', 'unsafe_rpc'):
            raise InternalException(msg='[smarthome] unsafe_rpc = off')
        path, args, kwargs = self._rpc_data_extractor(data)
        if cmd == 'call.plugin':
            try:
                entry = self.own.get_plugin(path[0])
            except RuntimeError as e:
                raise InternalException(code=3, msg=str(e))
            walked = ['plugins', path[0]]
            path = path[1:]
        elif cmd == 'call.global':
            try:
                entry = globals()[path[0]]
            except Exception as e:
                raise InternalException(code=3, msg='globals \'{}\' not found: {}'.format(path[0], e))
            walked = ['globals', path[0]]
            path = path[1:]
        else:
            entry = self.own
            walked = ['owner']

        return self._rpc_caller(entry, path, walked, args, kwargs)

    @staticmethod
    def _rpc_data_extractor(data: str) -> tuple:
        try:
            data = json.loads(data)
            if not isinstance(data, dict):
                raise TypeError('must be a dict type')
            path = data['path']
            if not isinstance(path, str):
                raise TypeError('Wring path type: {}'.format(type(path)))
            if not path:
                raise ValueError('Empty path')
            path = path.split('.')
            args = data.get('args', [])
            if not isinstance(args, list):
                raise TypeError('args must be a list type, get {}'.format(type(args)))
            kwargs = data.get('kwargs', {})
            if not isinstance(kwargs, dict):
                raise TypeError('kwargs must be a dict type, get {}'.format(type(kwargs)))
        except (json.decoder.JSONDecodeError, TypeError, KeyError, ValueError) as e:
            raise InternalException(code=2, msg='Wrong request: {}'.format(e))
        return path, args, kwargs

    @staticmethod
    def _rpc_caller(obj, path: list, walked: list, args: list, kwargs: dict):
        for target in path:
            obj = getattr(obj, target, None)
            if obj is None:
                raise InternalException(code=4, msg='method \'{}\' not found in \'{}\''.format(target, '.'.join(walked)))
            walked.append(target)
        try:
            result = obj(*args, **kwargs)
        except Exception as e:
            raise InternalException(code=5, msg='Call \'{}\' failed: {}'.format('.'.join(walked), e))
        if result is None or isinstance(result, (int, float, str, bool)):
            return result
        if isinstance(result, set):
            result = list(result)
        # Проверка на сериализуемость и repr
        try:
            json.dumps(result, ensure_ascii=False)
            return result
        except (TypeError, json.JSONDecoder, ValueError):
            pass
        try:
            return repr(result)
        except Exception as e:
            return 'result serialization error: {}'.format(e)


class APIHandler(API):
    def extract(self, line: str) -> tuple:
        if line.startswith('{'):
            return self._extract_json(line)
        else:
            return self._extract_str(line)

    def _extract_json(self, line: str) -> tuple:
        null = Null()
        try:
            line = json.loads(line)
            if not isinstance(line, dict):
                raise TypeError('must be a dict type')
        except (json.decoder.JSONDecodeError, TypeError) as e:
            raise InternalException(code=-32700, msg=str(e), id_=null)

        # Хак для ошибок парсинга, null != None
        id_ = line['id'] if line.get('id') is not None else null

        # Получили ответ с ошибкой.
        if 'error' in line and isinstance(line['error'], dict):
            code_ = repr(line['error'].get('code'))
            msg_ = repr(line['error'].get('message'))
            self.log('Error message received. code: {}, msg: {}, id: {}'.format(code_, msg_, repr(id_)), logger.WARN)
            raise RuntimeError

        # Получили ответ с результатом.
        if 'result' in line:
            result_ = line['result']
            if result_ and id_ == 'pong':
                self._api_pong(None, result_)
            else:
                self.log('Response message received. result: {}, id: {}'.format(repr(result_), repr(id_)), logger.INFO)
            raise RuntimeError

        # Запрос.
        method = line.get('method')
        if not method:
            raise InternalException(code=-32600, msg='method missing', id_=id_)
        if not isinstance(method, str):
            raise InternalException(code=-32600, msg='method must be a str', id_=id_)
        params = line.get('params')
        if params:
            # FIXME: legacy
            if isinstance(params, list) and len(params) == 1 and isinstance(params[0], str):
                params = params[0]
            elif isinstance(params, (dict, list)):
                # Обратно в строку - костыль.
                params = json.dumps(params)
            else:
                raise InternalException(code=-32602, msg='legacy, params must be a list[str]', id_=id_, method=method)
        else:
            params = ''

        # null == None
        id_ = None if isinstance(id_, Null) else id_
        return method, params, id_

    @staticmethod
    def _extract_str(line: str) -> tuple:
        line = line.split(':', 1)
        if len(line) != 2:
            line.append('')
        return line[0], line[1], None


class SocketAPIHandler(threading.Thread, APIHandler):
    # Канал для неблокирующих команд
    # Вызов: команда, данные
    NET = 'net'
    # Канал для блокирующих команд
    # Вызов: соманда, данные, блокировка, коннектор
    # Обработчик будет приостановлен на 60 сек или до вызова блокировки подписчиком.
    NET_BLOCK = 'net_block'

    def __init__(self, cfg, log, owner: Owner, name, duplex_mode=False):
        threading.Thread.__init__(self, name=name)
        APIHandler.__init__(self, cfg, log, owner)

        # Клиент получит ответ на все ошибки коммуникации
        self._duplex_mode = duplex_mode
        self.work = False
        self._conn = Connect(None, None, self.do_ws_allow)
        self._lock = Unlock()
        self.id = None
        # Команды API не требующие авторизации
        self.NON_AUTH = {
            'authorization', 'hi', 'voice', 'play', 'pause', 'tts', 'ask', 'settings', 'volume', 'volume_q', 'rec',
            'remote_log', 'music_volume', 'music_volume_q', 'listener',
        }

    @api_commands('authorization')
    def _authorization(self, cmd, remote_hash):
        if not self._conn.auth:
            token = self.cfg.gt('smarthome', 'token')
            if token:
                local_hash = hashlib.sha512(token.encode()).hexdigest()
                if local_hash != remote_hash:
                    raise InternalException(msg='forbidden: wrong hash')
            self._conn.auth = True
            msg = 'authorized'
            self.log('API.{} {}'.format(cmd, msg), logger.INFO)
            return msg
        return 'already'

    @api_commands('deauthorization')
    def _deauthorization(self, cmd, _):
        if self._conn.auth:
            self._conn.auth = False
            msg = 'deauthorized'
            self.log('API.{} {}'.format(cmd, msg), logger.INFO)
            return msg
        return 'already'

    def join(self, timeout=None):
        if self.work:
            self.work = False
            self._conn.close()
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

    def _call_api(self, cmd: str, data, id_):
        self.id = id_
        try:
            result = self.API[cmd](cmd, data)
        except RuntimeError as e:
            self.log('Error {}: {}'.format(cmd, e), logger.ERROR)
        except InternalException as e:
            e.id = id_
            self._handle_exception(e, cmd)
        except Exception as e:
            self._handle_exception(InternalException(code=-32603, msg=str(e), id_=id_), cmd, logger.CRIT)
        else:
            if id_ is not None:
                self._write({'result': result, 'id': id_})

    def _handle_exception(self, e: InternalException, cmd='method', code=0, log_lvl=logger.WARN):
        e.method = cmd
        e.cmd_code(code or self.API_CODE.get(cmd, 1000))
        self.log('API.{}'.format(e), log_lvl)
        if e.id is not None:
            self._write(e.data)

    def parse(self, data: str):
        def write_none():
            if id_ is not None:
                self._write({'result': None, 'id': id_})

        if not data:
            self._handle_exception(InternalException(code=-32600, msg='no data'))
            return
        else:
            self.log('Received data: {}'.format(repr(data)[:1500]))
        try:
            cmd, data, id_ = self.extract(data)
        except InternalException as e:
            self._handle_exception(e, e.method)
            return
        except RuntimeError:
            return

        if not self._conn.auth and cmd not in self.NON_AUTH:
            self._handle_exception(
                InternalException(code=0, msg='forbidden: authorization is necessary', id_=id_),
                cmd,
                self.API_CODE.get('authorization', 1000)
            )
        elif self.own.has_subscribers(cmd, self.NET):
            self.log('Command {} intercepted'.format(repr(cmd)))
            self.own.sub_call(self.NET, cmd, data)
            write_none()
        elif self.own.has_subscribers(cmd, self.NET_BLOCK):
            self.log('Command {} intercepted in blocking mode'.format(repr(cmd)))
            self._lock.clear()
            self.own.sub_call(self.NET_BLOCK, cmd, data, self._lock, self._conn)
            # Приостанавливаем выполнение, ждем пока обработчик нас разблокирует
            # 1 минуты хватит?
            self._lock.wait(60)
            write_none()
        elif cmd in self.API:
            self._call_api(cmd, data, id_)
        else:
            cmd = repr(cmd)[1:-1]
            msg = 'Unknown command: \'{}\''.format(cmd[:100])
            self._handle_exception(InternalException(code=-32601, msg=msg, id_=id_), cmd)

    def _write(self, data, quite=False):
        try:
            self._conn.write(data)
        except RuntimeError as e:
            self._conn.close()
            if not quite:
                self.log('Write error: {}'.format(e), logger.ERROR)


class Unlock(threading.Event):
    def __call__(self, *args, **kwargs):
        self.set()
