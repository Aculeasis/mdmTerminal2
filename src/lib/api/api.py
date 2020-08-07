import base64
import json
import os
import time

import logger
from lib.api.misc import (
    InternalException, api_commands, dict_key_checker, json_parser, dict_list_to_list_in_tuple, Null
)
from lib.map_settings.map_settings import make_map_settings
from owner import Owner
from utils import file_to_base64, pretty_time, TextBox, is_valid_base_filename

# old -> new
OLD_CMD = {
    'hi': 'voice',
    'volume_q': 'volume',
    'music_volume_q': 'mvolume'
}


class API:
    def __init__(self, cfg, log, owner: Owner):
        self.cfg, self.log, self.own = cfg, log, owner
        # Команды API не требующие авторизации
        self.NON_AUTH = {
            'hi', 'voice', 'play', 'pause', 'tts', 'ask',
            'settings', 'rec', 'remote_log', 'listener', 'volume', 'info',
            'nvolume', 'mvolume', 'nvolume_say', 'mvolume_say', 'get',
        }
        # Для подключения коллбэков
        self._getters, self._setters = {'auth': lambda : False}, {}
        self.API, self.API_CODE = {}, {}
        self.TRUE_JSON, self.TRUE_LEGACY, self.PURE_JSON, self.ALLOW_RESPONSE = set(), set(), set(), set()
        self._collector()

    @staticmethod
    def _up(dict_: dict, name: str or dict, callback):
        for name_, callback_ in ({name: callback} if isinstance(name, str) else name).items():
            if not name_:
                raise RuntimeError('Empty name')
            if not callback_:
                if name_ == '*':
                    dict_.clear()
                else:
                    dict_.pop(name_, None)
            else:
                dict_[name_] = callback_

    def getters_up(self, name: str or dict, callback=None):
        self._up(self._getters, name, callback)

    def setters_up(self, name: str or dict, callback=None):
        self._up(self._setters, name, callback)

    def get(self, name, *args, **kwargs):
        return self._getters[name](*args, **kwargs)

    def set(self, name, *args, **kwargs):
        return self._setters[name](*args, **kwargs)

    def _collector(self):
        def filling(target: set, name_):
            sets = getattr(obj, name_, None)
            if not (sets and isinstance(sets, tuple)):
                return
            for set_ in sets:
                if set_ in target:
                    raise RuntimeError('command {} already marked as {}'.format(set_, name_))
                target.add(set_)

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
            filling(self.TRUE_JSON, 'true_json')
            filling(self.TRUE_LEGACY, 'true_legacy')
            filling(self.PURE_JSON, 'pure_json')
            filling(self.ALLOW_RESPONSE, 'allow_response')
            # pure_json поддерживает только чистый json
            self.TRUE_JSON -= self.PURE_JSON
            self.TRUE_LEGACY -= self.PURE_JSON
        self.API_CODE = {name: index for index, name in enumerate(self.API.keys(), 1)}

    @api_commands('get', true_json=('get',), true_legacy=('get',))
    def _api_get(self, _, data):
        """
        Возвращает значение в зависимости от key вместе с ним самим.
        Возможные значения key - volume, nvolume, mvolume, mstate, listener.
        С JSON-RPC можно запросить несколько значений.
        """
        cmd_map = {
            'volume': self.own.get_volume,
            'nvolume': self.own.get_volume,
            'mvolume': lambda : self.own.music_real_volume,
            'mstate': self.own.music_state,
            'listener': self.own.terminal_listen,
        }

        def get_value(key):
            if key not in cmd_map:
                raise InternalException(msg='Unknown command: {}'.format(repr(key)))
            value = cmd_map[key]()
            return value if value is not None else -1

        return {key: get_value(key) for key in data}

    @api_commands('home', 'url', 'rts', 'run')
    def _api_no_implement(self, cmd: str, _):
        """NotImplemented"""
        raise InternalException(msg='Not implemented yet - {}'.format(cmd))

    @api_commands('hi', 'voice', 'volume', 'nvolume', 'mvolume', 'nvolume_say', 'mvolume_say', 'listener',
                  'volume_q', 'music_volume_q')
    def _api_terminal_direct(self, name: str, cmd: str):
        self.own.terminal_call(OLD_CMD[name] if name in OLD_CMD else name, cmd)

    @api_commands('ask', true_json=True)
    def _api_ask(self, cmd, data):
        """
        Произнести текст и перейти в режим ожидания голосовой команды.

        JSON-RPC использует другой синтаксис и позволяет опционально задать провайдера:
        {"method": "ask", "params": {"text": "скажи привет", "provider": "rhvoice-rest"}}
        """
        self._base_says(cmd, data)

    @api_commands('tts', true_json=True)
    def _api_tts(self, cmd, data):
        """
        Произнести текст.

        JSON-RPC использует другой синтаксис и позволяет опционально задать провайдера:
        {"method": "tts", "params": {"text": "привет", "provider": "google"}}
        """
        self._base_says(cmd, data)

    def _base_says(self, cmd, data):
        data = data if isinstance(data, dict) else {'text': data[0] if isinstance(data, list) and data else data}
        dict_key_checker(data, keys=('text',))
        self.own.terminal_call(cmd, TextBox(data['text'], data.get('provider')))

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
        if len([1 for x in param if len(x)]) != 3:
            raise InternalException(msg='Error parsing parameters for \'rec\': {}'.format(repr(param)[:1500]))
        # a = param[0] # rec, play или compile
        # b = param[1] # 1-6
        # c = param[2] # 1-3
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
        if not self.cfg.detector.is_model_name(data['filename']):
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
        if not self.cfg.detector.is_model_name(pmdl_name):
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

    @api_commands('test.record', pure_json=True)
    def _api_test_recoder(self, _, data):
        """file: str, limit: [int, float]"""
        dict_key_checker(data, ('file',))
        file, limit = data['file'], data.get('limit', 8)
        if not isinstance(limit, (int, float)):
            raise InternalException(msg='limit must be int or float, not {}'.format(type(limit)))
        if not 3 <= limit <= 3600:
            raise InternalException(code=2, msg='3 <= limit <= 3600, get {}'.format(limit))
        if not isinstance(file, str):
            raise InternalException(code=3, msg='file must be str, not {}'.format(type(file)))
        if not file:
            raise InternalException(code=4, msg='file empty')
        self.own.terminal_call('test.record', (file, limit))

    @api_commands('test.play', 'test.delete', pure_json=True)
    def _api_test_play_delete(self, cmd, data):
        """files: list[str]"""
        self.own.terminal_call(cmd, dict_list_to_list_in_tuple(data, ('files',)))

    @api_commands('test.test', pure_json=True)
    def _api_test_test(self, _, data):
        """providers: list[str], files: list[str]"""
        self.own.terminal_call('test.test', dict_list_to_list_in_tuple(data, ('providers', 'files')))

    @api_commands('test.list', pure_json=True)
    def _api_test_list(self, *_):
        return self.cfg.get_all_testfile()

    @staticmethod
    @api_commands('ping', true_json=True)
    def _api_ping(_, data: str):
        """
        Пустая команда для поддержания и проверки соединения,
        вернет данные, если данные пустые вернет строку с текущим time.time().
        """
        return data if data else str(time.time())

    @api_commands('pong', allow_response=True)
    def _api_pong(self, _, data: str):
        """Считает пинг"""
        if data:
            try:
                data = time.time() - float(data)
            except (ValueError, TypeError):
                pass
            else:
                self.log('Ping {}'.format(pretty_time(data)), logger.INFO)

    @api_commands('info')
    def _api_info(self, _, cmd: str) -> dict:
        """
        Возвращает справку по команде из __doc__ или список доступных команд если команда не задана.
        Учитывает только команды представленные в API, подписчики не проверяются.
        """
        def allow(cmd_):
            return self.get('auth') or cmd_ in self.NON_AUTH

        def flags2(cmd_):
            return [cmd_ in x for x in (self.TRUE_JSON, self.PURE_JSON)]

        result = {'cmd': cmd, 'msg': ''}
        if not cmd:
            result.update(cmd=[x for x in self.API if allow(x)], msg='Available commands')
        elif cmd == '*':
            result.update(cmd={x: flags2(x) for x in self.API if allow(x)}, msg='Flags: TRUE_JSON, PURE_JSON')
        elif not (cmd in self.API and allow(cmd)):
            raise InternalException(msg='Unknown command: {}'.format(cmd))
        else:
            if self.API[cmd].__doc__:
                result['msg'] = self.API[cmd].__doc__.strip('\n').rstrip()
            result['msg'] = result['msg'] or 'Undocumented'
            flags = [k for k, s in (
                ('TRUE_JSON', self.TRUE_JSON), ('TRUE_LEGACY', self.TRUE_LEGACY),
                ('PURE_JSON', self.PURE_JSON), ('ALLOW_RESPONSE', self.ALLOW_RESPONSE),
                ('NON_AUTH', self.NON_AUTH),
            ) if cmd in s]
            if flags:
                result['flags'] = flags
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

    @api_commands('call.plugin')  # @api_commands('call.plugin', 'call.owner', 'call.global')
    def _api_rpc_call(self, cmd: str, data: str):
        if not self.cfg.gt('smarthome', 'unsafe_rpc'):
            raise InternalException(msg='[smarthome] unsafe_rpc = off')
        path, args, kwargs = _rpc_data_extractor(data)
        for key in path:
            if key.startswith('_'):
                raise InternalException(code=4, msg='Private path \'{}\' - ignore'.format(key))
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

        return _rpc_caller(entry, path, walked, args, kwargs)

    @api_commands('maintenance.reload', 'maintenance.stop')
    def _api_maintenance(self, cmd: str, *_):
        self.own.die_in(3, reload=cmd.endswith('.reload'))

    @api_commands('backup.manual')
    def _api_backup_manual(self, *_):
        self.own.backup_manual()

    @api_commands('backup.restore')
    def _api_backup_restore(self, _, data):
        if not data:
            raise InternalException(msg='Empty filename')
        if not is_valid_base_filename(data):
            raise InternalException(2, 'Wrong filename')
        files = self.own.backup_list()
        if not files:
            raise InternalException(3, 'No backups')
        if data == 'last':
            filename, timestamp = files[0]
        else:
            filename, timestamp = next((item for item in files if item[0] == data), (None, None))
            if not filename:
                raise InternalException(4, 'File no found: {}'.format(data))
        self.own.backup_restore(filename)
        return {'filename': filename, 'timestamp': timestamp}

    @api_commands('backup.list')
    def _api_backup_list(self, *_) -> list:
        return [{'filename': filename, 'timestamp': timestamp} for filename, timestamp in self.own.backup_list()]


class BaseAPIHandler(API):
    IS_METHOD = 'method'
    IS_RESULT = 'result'
    IS_ERROR = 'error'
    ALL_TYPES = (IS_METHOD, IS_RESULT, IS_ERROR)

    def __init__(self, cfg, log, owner: Owner):
        super().__init__(cfg, log, owner)
        self.is_jsonrpc = False
        self.id = None

    def call(self, data: dict) -> dict or None:
        if data['type'] == 'cmd':
            return self.call_api(data)
        elif data['type'] == 'result':
            return self.call_result(data)
        elif data['type'] == 'error':
            return self.has_error(data)
        raise RuntimeError

    def call_api(self, data: dict) -> dict or None:
        if data['cmd'] not in self.API:
            cmd = repr(data['cmd'])[1:-1]
            msg = 'Unknown command: \'{}\''.format(cmd[:100])
            raise InternalException(code=-32601, msg=msg, id_=data['id'])

        self.id = data['id']
        result = self.API[data['cmd']](data['cmd'], data['params'])
        return {'result': result, 'id': data['id']} if data['id'] is not None else None

    def call_result(self, data: dict) -> None:
        if data['id'] in self.ALLOW_RESPONSE:
            self.API[data['id']](data['id'], data['result'])
        else:
            data = {k: repr(v) for k, v in data.items()}
            self.log('Response message received. result: {result}, id: {id}, JSON_RPC: {jsonrpc}'.format(
                **data, jsonrpc=self.is_jsonrpc
            ), logger.INFO)
        return None

    def has_error(self, data: dict) -> None:
        data = {k: repr(v) for k, v in data.items()}
        self.log('Error message received. code: {code}, msg: {message}, id: {id}'.format(**data), logger.WARN)
        return None

    def extract(self, line: str or dict) -> dict:
        return self._extract_json(line) if self.is_jsonrpc else self._extract_str(line)

    def prepare(self, line: str, is_json=None) -> str or dict or list:
        self.is_jsonrpc = is_json if is_json is not None else (line.startswith('{') or line.startswith('['))
        if self.is_jsonrpc:
            try:
                line = json.loads(line)
                if not isinstance(line, (dict, list)):
                    raise InternalException(code=-32700, msg='must be a dict or list type', id_=Null)
            except (json.decoder.JSONDecodeError, TypeError) as e:
                raise InternalException(code=-32700, msg=str(e), id_=Null)
        return line

    def _extract_json(self, line: dict) -> dict:
        def get_id():
            return None if id_ is Null else id_

        if not isinstance(line, dict):
            raise InternalException(code=-32600, msg='must be a dict type', id_=Null)

        # Хак для ошибок парсинга, null != None
        id_ = line['id'] if line.get('id') is not None else Null

        found = [key for key in self.ALL_TYPES if key in line]
        if len(found) != 1:
            msg = 'Only one key of {} may present, found: {}'.format(self.ALL_TYPES, tuple(found) if found else '')
            raise InternalException(code=-32600, msg=msg, id_=id_)
        found = found[0]

        if found == self.IS_METHOD:
            # Запрос.
            method = line[self.IS_METHOD]
            if not isinstance(method, str):
                raise InternalException(code=-32600, msg='{} must be a str'.format(self.IS_METHOD), id_=id_)
            self._check_auth(method, get_id())

            params = line.get('params')
            if method in self.PURE_JSON:
                if params is not None and not isinstance(params, (dict, list)):
                    raise InternalException(
                        code=-32600, msg='params must be a dict, list or null', id_=id_, method=method
                    )
            elif method in self.TRUE_JSON and isinstance(params, (dict, list)):
                pass
            elif params:
                # FIXME: legacy
                if isinstance(params, list) and len(params) == 1 and isinstance(params[0], str):
                    params = params[0]
                elif isinstance(params, (dict, list)):
                    # Обратно в строку - костыль.
                    params = json.dumps(params)
                else:
                    raise InternalException(
                        code=-32602, msg='legacy, params must be a list[str]', id_=id_, method=method
                    )
            else:
                params = ''
            return {'type': 'cmd', 'cmd': method, 'params': params, 'id': get_id()}
        elif found == self.IS_ERROR:
            # Получили ответ с ошибкой.
            if isinstance(line[self.IS_ERROR], dict):
                return {
                    'type': 'error',
                    'code': line[self.IS_ERROR].get('code'),
                    'message': line[self.IS_ERROR].get('message'),
                    'id': get_id()
                }
            raise InternalException(code=-32600, msg='{} myst be a dict'.format(self.IS_ERROR))
        elif found == self.IS_RESULT:
            # Получили ответ с результатом.
            _id = get_id()
            if _id and _id in self.ALLOW_RESPONSE:
                self._check_auth(_id, None)
            return {'type': 'result', 'result': line[self.IS_RESULT], 'id': _id}
        raise RuntimeError

    def _extract_str(self, line: str) -> dict:
        line = line.split(':', 1)
        if len(line) != 2:
            line.append('')
        # id = cmd
        cmd = line[0]
        self._check_auth(cmd, cmd)
        if cmd in self.PURE_JSON:
            InternalException(code=-32700, msg='Allow only in JSON-RPC', id_=cmd, method=cmd)
        data = [line[1]] if cmd in self.TRUE_JSON else line[1]
        return {'type': 'cmd', 'cmd': cmd, 'params': data, 'id': cmd}

    def _check_auth(self, method, id_):
        if not self.get('auth') and method not in self.NON_AUTH:
            raise InternalException(
                code=self.API_CODE.get('authorization', 1000),
                msg='forbidden: authorization is necessary',
                id_=id_,
                method=method
            )


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


def _rpc_caller(obj, path: list, walked: list, args: list, kwargs: dict):
    for target in path:
        obj = getattr(obj, target, None)
        if obj is None:
            msg = 'method \'{}\' not found in \'{}\''.format(target, '.'.join(walked))
            raise InternalException(code=4, msg=msg)
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
