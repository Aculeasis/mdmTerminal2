import json
import threading

import logger
from lib.api.misc import InternalException, Null, SelfAuthInstance, Unlock
from lib.socket_wrapper import Connect
from owner import Owner


class APIParser:
    def __init__(self):
        self.API, self.API_CODE = {}, {}
        self.TRUE_JSON, self.TRUE_LEGACY, self.PURE_JSON = set(), set(), set()
        self._collector()

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
            # С pure_json данные всегда в json
            self.TRUE_JSON |= self.PURE_JSON
            # pure_json поддерживает только чистый json
            self.TRUE_LEGACY -= self.PURE_JSON
        self.API_CODE = {name: index for index, name in enumerate(self.API.keys(), 1)}


class APIHandler(APIParser):
    def __init__(self, log):
        super().__init__()
        self.log = log
        self.is_jsonrpc = False

    def extract(self, line: str or dict) -> tuple:
        return self._extract_json(line) if self.is_jsonrpc else self._extract_str(line)

    def prepare(self, line: str) -> str or dict or list:
        if line.startswith('{') or line.startswith('['):
            self.is_jsonrpc = True
            try:
                line = json.loads(line)
                if not isinstance(line, (dict, list)):
                    raise InternalException(code=-32700, msg='must be a dict or list type', id_=Null())
            except (json.decoder.JSONDecodeError, TypeError) as e:
                raise InternalException(code=-32700, msg=str(e), id_=Null())
        else:
            self.is_jsonrpc = False
        return line

    def _extract_json(self, line: dict) -> tuple:
        null = Null()
        if not isinstance(line, dict):
            raise InternalException(code=-32600, msg='must be a dict type', id_=null)
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
            if id_ == 'pong' and id_ in self.API and result_:
                self.API[id_](None, result_)
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
        if method in self.TRUE_JSON and isinstance(params, (dict, list)):
            pass
        elif params:
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

    def _extract_str(self, line: str) -> tuple:
        line = line.split(':', 1)
        if len(line) != 2:
            line.append('')
        # id = cmd
        cmd = line[0]
        data = [line[1]] if cmd in self.TRUE_JSON else line[1]
        return cmd, data, cmd


class SocketAPIHandler(threading.Thread, APIHandler):
    # Канал для неблокирующих команд
    # Вызов: команда, данные
    NET = 'net'
    # Канал для блокирующих команд
    # Вызов: команда, данные, блокировка, коннектор
    # Обработчик будет приостановлен на 60 сек или до вызова блокировки подписчиком.
    NET_BLOCK = 'net_block'

    def __init__(self, log, owner: Owner, name):
        threading.Thread.__init__(self, name=name)
        APIHandler.__init__(self, log)
        self.own = owner

        self.work = False
        self._conn = Connect(None, None, self.do_ws_allow)
        self._lock = Unlock()
        self.id = None
        self.NON_AUTH = set()

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

    @staticmethod
    def _get_owner_callback(name: str):
        return SelfAuthInstance().owner_cb(name)

    def _call_api(self, cmd: str, data, id_) -> dict or None:
        self.id = id_
        try:
            result = self.API[cmd](cmd, data)
            return {'result': result, 'id': id_} if id_ is not None else None
        except InternalException as e:
            e.id = id_
            return self._handle_exception(e, cmd)
        except RuntimeError as e:
            self.log('API.{} RuntimeError: {} '.format(cmd, e), logger.ERROR)
        except Exception as e:
            try:
                name = e.__class__.__name__
            except AttributeError:
                name = ''
            self.log('API.{} {}: {} '.format(cmd, name or 'Exception', e), logger.CRIT)
        return None

    def __processing(self, data: dict or str) -> dict or None:
        def none():
            return {'result': None, 'id': id_} if id_ is not None else None

        try:
            cmd, data, id_ = self.extract(data)
        except InternalException as e:
            return self._handle_exception(e, e.method)
        except RuntimeError:
            return None

        if not self._conn.auth and cmd not in self.NON_AUTH:
            return self._handle_exception(
                InternalException(code=0, msg='forbidden: authorization is necessary', id_=id_),
                cmd,
                self.API_CODE.get('authorization', 1000)
            )
        if cmd in self.PURE_JSON:
            if not self.is_jsonrpc:
                return self._handle_exception(
                    InternalException(code=-32700, msg='Allow only in JSON-RPC', id_=id_), cmd
                )
            elif data is not None and not isinstance(data, (dict, list)):
                return self._handle_exception(
                    InternalException(code=-32600, msg='params must be a dict or list', id_=id_), cmd
                )

        if self.own.has_subscribers(cmd, self.NET):
            self.log('Command {} intercepted'.format(repr(cmd)))
            self.own.sub_call(self.NET, cmd, data)
            return none()
        if self.own.has_subscribers(cmd, self.NET_BLOCK):
            self.log('Command {} intercepted in blocking mode'.format(repr(cmd)))
            self._lock.clear()
            self.own.sub_call(self.NET_BLOCK, cmd, data, self._lock, self._conn)
            # Приостанавливаем выполнение, ждем пока обработчик нас разблокирует
            # 1 минуты хватит?
            self._lock.wait(60)
            return none()
        if cmd in self.API:
            return self._call_api(cmd, data, id_)

        cmd = repr(cmd)[1:-1]
        msg = 'Unknown command: \'{}\''.format(cmd[:100])
        return self._handle_exception(InternalException(code=-32601, msg=msg, id_=id_), cmd)

    def _parse(self, data: str):
        if not data:
            return self._handle_exception(InternalException(code=-32600, msg='no data'))
        else:
            self.log('Received data: {}'.format(repr(data)[:1500]))

        try:
            data = self.prepare(data)
        except InternalException as e:
            return self._handle_exception(e, e.method)

        if not (self.is_jsonrpc and isinstance(data, list)):
            return self.__processing(data)
        # JSON-RPC Batch
        return [x for x in [self.__processing(cmd) for cmd in data] if x is not None] or None

    def parse(self, data: str):
        result = self._parse(data)
        if result is not None:
            self._send_reply(result)

    def _handle_exception(self, e: InternalException, cmd='method', code=0, log_lvl=logger.WARN) -> dict or None:
        e.method = cmd
        e.cmd_code(code or self.API_CODE.get(cmd, 1000))
        self.log('API.{}'.format(e), log_lvl)
        return e.data if e.id is not None else None

    def _send_reply(self, data: dict):
        if self.is_jsonrpc:
            self._write(data)
        else:
            cmd = data.pop('id', None)
            if not cmd or cmd == 'method':
                return
            reply = None
            if cmd in self.TRUE_LEGACY:
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
