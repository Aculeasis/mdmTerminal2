import hashlib
import json
import threading
import time

import logger
from lib.api.api import BaseAPIHandler, dict_key_checker
from lib.api.misc import InternalException, SelfAuthInstance, Unlock, api_commands
from lib.socket_wrapper import Connect
from lib.totp_salt import check_token_with_totp
from owner import Owner
from utils import pretty_time


class APIHandler(BaseAPIHandler):
    def __init__(self, cfg, log, owner: Owner):
        super().__init__(cfg, log, owner)
        self.NON_AUTH.update({'authorization', 'authorization.self', 'authorization.totp'})

    def _base_authorization(self, cmd, equal, sub_msg='') -> str:
        # compare(token) -> bool
        if not self.get('auth'):
            token = self.cfg.gt('smarthome', 'token')
            if token:
                if not equal(token):
                    raise InternalException(msg='forbidden: wrong hash{}'.format(sub_msg))
            self.set('auth', True)
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
        if not self.get('auth'):
            fun = self.get('owner_callback', data['owner'])
            if not fun:
                raise InternalException(3, 'Unknown owner - {}'.format(data['owner']))
            if not fun(data['token'], self.get('ip'), self.get('port')):
                raise InternalException(4, 'forbidden: rejected')
            self.set('auth', True)
            msg = 'authorized'
            self.log('API.{} {} from {}'.format(cmd, msg, repr(data['owner'])), logger.INFO)
            return msg
        return 'already'

    @api_commands('deauthorization')
    def _api_deauthorization(self, cmd, _):
        """Отменяет авторизацию для текущего подключения."""
        if self.get('auth'):
            self.set('auth', False)
            msg = 'deauthorized'
            self.log('API.{} {}'.format(cmd, msg), logger.INFO)
            return msg
        return 'already'


class SocketAPIHandler(threading.Thread):
    # Канал для неблокирующих команд
    # Вызов: команда, данные
    NET = 'net'
    # Канал для блокирующих команд
    # Вызов: команда, данные, блокировка, коннектор
    # Обработчик будет приостановлен на 60 сек или до вызова блокировки подписчиком.
    NET_BLOCK = 'net_block'

    def __init__(self, cfg, log, owner: Owner, name, api_handler=APIHandler):
        super().__init__(name=name)
        self.cfg, self.log, self.own = cfg, log, owner

        self.work = False
        self._conn = Connect(None, None, self.do_ws_allow)
        self._lock = Unlock()

        def set_auth(auth):
            self._conn.auth = auth

        self.api = api_handler(cfg, log, owner)
        self.api.setters_up({'auth': set_auth})
        self.api.getters_up({
            'auth': lambda : self._conn.auth,
            'ip': lambda : self._conn.ip,
            'port': lambda : self._conn.port,
            'owner_callback': lambda x: SelfAuthInstance().owner_cb(x)
        })

    def join(self, timeout=30):
        SelfAuthInstance().unsubscribe(self.own)
        self._conn.close()
        super().join(timeout=timeout)

    def start(self):
        if not self.work:
            self.work = True
            SelfAuthInstance().subscribe(self.own)
            super().start()
            self.log('start', logger.INFO)

    def do_ws_allow(self, ip, port, token):
        raise NotImplemented

    def run(self):
        raise NotImplemented

    def _call_api(self, data: dict) -> dict or None:
        def cmd():
            return data['cmd'] if data['type'] == 'cmd' else data.get('id')

        try:
            return self.api.call(data)
        except InternalException as e:
            e.id = data.get('id')
            return self._handle_exception(e, cmd())
        except RuntimeError as e:
            self.log('API.{} RuntimeError: {} '.format(cmd(), e), logger.ERROR)
        except Exception as e:
            try:
                name = e.__class__.__name__
            except AttributeError:
                name = ''
            self.log('API.{} {}: {} '.format(cmd(), name or 'Exception', e), logger.CRIT)
        return None

    def __processing(self, data: dict or str) -> dict or None:
        def none():
            return {'result': None, 'id': data['id']} if data['id'] is not None else None

        try:
            data = self.api.extract(data)
        except InternalException as e:
            return self._handle_exception(e, e.method)
        if data['type'] == 'error':
            return self.api.has_error(data)

        if data['type'] == 'cmd':
            if self.own.has_subscribers(data['cmd'], self.NET):
                self.log('Command {} intercepted'.format(repr(data['cmd'])))
                self.own.sub_call(self.NET, data['cmd'], data['params'])
                return none()
            if self.own.has_subscribers(data['cmd'], self.NET_BLOCK):
                self.log('Command {} intercepted in blocking mode'.format(repr(data['cmd'])))
                self._lock.clear()
                self.own.sub_call(self.NET_BLOCK, data['cmd'], data['params'], self._lock, self._conn)
                # Приостанавливаем выполнение, ждем пока обработчик нас разблокирует
                # 1 минуты хватит?
                self._lock.wait(60)
                return none()
        result = self._call_api(data)
        return result if data['type'] == 'cmd' else None

    def _parse(self, data: str):
        if not data:
            return self._handle_exception(InternalException(code=-32600, msg='no data'))
        else:
            self.log('Received data: {}'.format(repr(data)[:1500]))

        try:
            data = self.api.prepare(data)
        except InternalException as e:
            return self._handle_exception(e, e.method)

        if not (self.api.is_jsonrpc and isinstance(data, list)):
            return self.__processing(data)
        # JSON-RPC Batch
        return [x for x in [self.__processing(cmd) for cmd in data] if x is not None] or None

    def parse(self, data: str):
        result = self._parse(data)
        if result is not None:
            self._send_reply(result)

    def _handle_exception(self, e: InternalException, cmd='method', code=0, log_lvl=logger.WARN) -> dict or None:
        e.method = cmd
        e.cmd_code(code or self.api.API_CODE.get(cmd, 1000))
        self.log('API.{}'.format(e), log_lvl)
        return e.data if e.id is not None else None

    def _send_reply(self, data: dict):
        if self.api.is_jsonrpc:
            self._write(data)
        else:
            cmd = data.pop('id', None)
            if not cmd or cmd == 'method':
                return
            reply = None
            if cmd in self.api.TRUE_LEGACY:
                result = data.get('result')
                if isinstance(result, (int, float, str)):
                    reply = '{}:{}'.format(cmd, result)
                elif result and isinstance(result, dict):
                    reply = ';'.join('{}:{}'.format(key, val) for key, val in result.items())
            try:
                reply = reply or '{}:{}'.format(cmd, json.dumps(data, ensure_ascii=False))
            except TypeError:
                return
            self._write(reply, True)

    def _write(self, data, quite=False):
        if not self._conn.alive:
            return
        try:
            self._conn.write(data)
        except RuntimeError as e:
            self._conn.close()
            if not quite:
                self.log('Write error: {}'.format(e), logger.ERROR)
