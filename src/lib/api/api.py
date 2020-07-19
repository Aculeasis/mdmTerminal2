import base64
import hashlib
import json
import os
import time

import logger
from lib.api.misc import InternalException, api_commands, dict_key_checker, json_parser, dict_list_to_list_in_tuple
from lib.api.socket_api_handler import SocketAPIHandler
from lib.map_settings.map_settings import make_map_settings
from lib.totp_salt import check_token_with_totp
from owner import Owner
from utils import file_to_base64, pretty_time, TextBox, is_valid_base_filename, deprecated

# old -> new
OLD_CMD = {
    'hi': 'voice',
    'volume_q': 'volume',
    'music_volume_q': 'mvolume'
}


class API(SocketAPIHandler):
    def __init__(self, cfg, log, owner: Owner, name):
        super().__init__(log, owner, name)
        self.cfg = cfg
        # Команды API не требующие авторизации
        self.NON_AUTH.update({
            'authorization', 'self.authorization', 'authorization.self', 'authorization.totp',
            'hi', 'voice', 'play', 'pause', 'tts', 'ask',
            'settings', 'rec', 'remote_log', 'listener', 'volume',
            'nvolume', 'mvolume', 'nvolume_say', 'mvolume_say', 'get',
        })

    def _base_authorization(self, cmd, equal, sub_msg='') -> str:
        # compare(token) -> bool
        if not self._conn.auth:
            token = self.cfg.gt('smarthome', 'token')
            if token:
                if not equal(token):
                    raise InternalException(msg='forbidden: wrong hash{}'.format(sub_msg))
            self._conn.auth = True
            msg = 'authorized'
            self.log('API.{} {}{}'.format(cmd, msg, sub_msg), logger.INFO)
            return msg
        return 'already'

    @api_commands('authorization')
    def _api_authorization(self, cmd, remote_hash):
        """Авторизация, повышает привилегии текущего подключения."""
        return self._base_authorization(cmd, lambda token: hashlib.sha512(token.encode()).hexdigest() == remote_hash)

    @api_commands('authorization.totp', pure_json=True)
    def _api_authorization_totp(self, cmd, data):
        """
        Перед хешированием токена добавляет к нему "соль" - Unix time поделенный на 2 и округленный до целого.
        Хеш будет постоянно меняться, но требует чтобы время на терминале и подключаемом устройстве точно совпадало.
        Также можно передать timestamp, он не участвует в хешировании но позволит узнать временную разницу:

        {"method":"authorization.totp","params":{"hash":"3a2af9d519e51c5bff2e283f2a3d384c6ey0721cb1d715ef356508c57bf1544c498328c59f5670e4aeb6bda135497f4e310960a77f88a046d2bb4185498d941f","timestamp":1582885520.931},"id":"8a5559310b336bad7e139550b7f648ad"}
        """
        time_ = time.time()
        dict_key_checker(data, ('hash',))
        remote_hash = data['hash']
        if not isinstance(remote_hash, str):
            raise InternalException(2, 'hash must be str, not {}'.format(type(remote_hash)))
        if 'timestamp' in data:
            timestamp = data['timestamp']
            if not isinstance(timestamp, float):
                raise InternalException(2, 'timestamp must be float, not {}'.format(type(timestamp)))
        else:
            timestamp = None
        time_diff = '; diff: {}'.format(pretty_time(time_ - timestamp)) if timestamp else ''
        return self._base_authorization(cmd, lambda token: check_token_with_totp(token, remote_hash, time_), time_diff)

    @api_commands('self.authorization', pure_json=True)
    @deprecated
    def _api_self_authorization(self, cmd, data: dict):
        return self._api_authorization_self(cmd, data)

    @api_commands('authorization.self', pure_json=True)
    def _api_authorization_self(self, cmd, data: dict):
        """
        Альтернативный способ авторизации, для внутренних нужд:

        {"method": "authorization.self", "params": {"token": "token", "owner": "owner"}}
        """
        keys = ('token', 'owner')
        dict_key_checker(data, keys)
        for key in keys:
            if not isinstance(data[key], str):
                raise InternalException(msg='Value in {} must be str, not {}.'.format(key, type(data[key])))
            if not data[key]:
                raise InternalException(2, 'Empty key - {}.'.format(key))
        if not self._conn.auth:
            fun = self._get_owner_callback(data['owner'])
            if not fun:
                raise InternalException(3, 'Unknown owner - {}'.format(data['owner']))
            if not fun(data['token'], self._conn.ip, self._conn.port):
                raise InternalException(4, 'forbidden: rejected')
            self._conn.auth = True
            msg = 'authorized'
            self.log('API.{} {} from {}'.format(cmd, msg, repr(data['owner'])), logger.INFO)
            return msg
        return 'already'

    @api_commands('deauthorization')
    def _api_deauthorization(self, cmd, _):
        """Отменяет авторизацию для текущего подключения."""
        if self._conn.auth:
            self._conn.auth = False
            msg = 'deauthorized'
            self.log('API.{} {}'.format(cmd, msg), logger.INFO)
            return msg
        return 'already'

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
        data = data if isinstance(data, dict) else {'text': data[0]}
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
        # file: str, limit: [int, float]
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
        # files: list[str]
        self.own.terminal_call(cmd, dict_list_to_list_in_tuple(data, ('files',)))

    @api_commands('test.test', pure_json=True)
    def _api_test_test(self, _, data):
        # providers: list[str], files: list[str]
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

    @api_commands('pong')
    def _api_pong(self, _, data: str):
        if data:
            # Считаем пинг
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
        result = {'cmd': cmd, 'msg': ''}
        if not cmd:
            result.update(cmd=[x for x in self.API], msg='Available commands')
        elif cmd not in self.API:
            raise InternalException(msg='Unknown command: {}'.format(cmd))
        else:
            if self.API[cmd].__doc__:
                result['msg'] = self.API[cmd].__doc__.strip('\n').rstrip()
            result['msg'] = result['msg'] or 'Undocumented'
            flags = [k for k, s in (
                ('TRUE_JSON', self.TRUE_JSON), ('TRUE_LEGACY', self.TRUE_LEGACY), ('PURE_JSON', self.PURE_JSON)
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
            filename, timestamp = files[-1]
        else:
            filename, timestamp = next((item for item in files if item[0] == data), (None, None))
            if not filename:
                raise InternalException(4, 'File no found: {}'.format(data))
        self.own.backup_restore(filename)
        return {'filename': filename, 'timestamp': timestamp}

    @api_commands('backup.list')
    def _api_backup_list(self, *_) -> list:
        return [{'filename': filename, 'timestamp': timestamp} for filename, timestamp in self.own.backup_list()]


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
