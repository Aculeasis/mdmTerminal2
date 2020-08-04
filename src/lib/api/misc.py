import json
import threading

from lib.socket_wrapper import Connect
from owner import Owner
from utils import singleton

SELF_AUTH_CHANNEL = 'net.self.auth'


class Null:
    @classmethod
    def __repr__(cls):
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
        return {'error': self.error, 'id': None if self.id is Null else self.id}

    def __str__(self):
        return '{} {code}: {message}'.format(self.method, **self.error)


class Unlock(threading.Event):
    def __call__(self, *args, **kwargs):
        self.set()


@singleton
class SelfAuthInstance:
    def __init__(self):
        self._lock = threading.Lock()
        self._owners = dict()
        self._events = ('add', 'remove')
        self._subscribers = 0

    def _cb(self, event: str, name: str, fun: callable, *_):
        """fun(token: str, ip: str, port: int) -> bool:"""
        if not name or not callable(fun):
            raise RuntimeError('Wrong callback: {}, {}, {}'.format(event, name, fun))
        if event == 'add':
            self._owners[name] = fun
        elif event == 'remove':
            self._owners.pop(name, None)
        else:
            raise RuntimeError('Wrong callback: {}, {}, {}'.format(event, name, fun))

    def owner_cb(self, name: str) -> callable or None:
        return self._owners.get(name)

    def subscribe(self, own: Owner):
        with self._lock:
            self._subscribers += 1
            if self._subscribers == 1:
                own.subscribe(self._events, self._cb, SELF_AUTH_CHANNEL)

    def unsubscribe(self, own: Owner):
        with self._lock:
            if not self._subscribers:
                return
            self._subscribers -= 1
            if not self._subscribers:
                own.unsubscribe(self._events, self._cb, SELF_AUTH_CHANNEL)
                self._owners.clear()


def api_commands(*commands, true_json=None, true_legacy=None, pure_json=None, allow_response=None):
    """
    Враппер для связывания команд с методом.
    :param commands: Список команд.
    :param true_json: Список команд, при обработке которых в data, будет исходный params а не строка,
    для старых команд будет ['<str>']. True - эквивалентно commands (тут и далее).
    :param true_legacy: Если обработчик вернет dict, передаст только его в строке ('key:val', 'key:val;key2:val2')
    или строку из 'cmd:result' без преобразования в json если result простой тип.
    :param pure_json: Список команд, которые доступны только в JSON-RPC.
    :param allow_response: Может обработать ответ, примитивно только если команда совпала с id.
    :return: Исходный метод.
    """
    def _commands(_flags):
        return commands if isinstance(_flags, bool) and _flags else _flags

    def filling(f, attr, data):
        if data:
            for command in data:
                if not (isinstance(command, str) and command):
                    raise RuntimeError('{} command must be a non empty string: {}'.format(f, command))
            setattr(f, attr, data)

    def wrapper(f):
        filling(f, 'api_commands', commands)
        filling(f, 'true_json', _commands(true_json))
        filling(f, 'true_legacy', _commands(true_legacy))
        filling(f, 'pure_json', _commands(pure_json))
        filling(f, 'allow_response', _commands(allow_response))
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
    except (json.decoder.JSONDecodeError, TypeError) as e:
        raise InternalException(msg=e)
    dict_key_checker(data, keys)
    return data


def dict_key_checker(data: dict, keys: tuple):
    if not isinstance(data, dict):
        raise InternalException(4, 'Data must be dict type')
    for key in keys:
        if key not in data:
            raise InternalException(5, 'Missing key: {}'.format(key))


def dict_list_to_list_in_tuple(data: dict, keys: tuple, types=(str,)) -> tuple:
    dict_key_checker(data, keys=keys)
    result = []
    for key in keys:
        value = data[key] if isinstance(data[key], list) else [data[key]]
        if not value:
            raise InternalException(6, '{} empty'.format(repr(key)))
        for idx, test in enumerate(value):
            if not isinstance(test, types):
                msg = '{0} must be list[{1}] or {1}, wrong type of #{2} - {3}'.format(repr(key), types, idx, type(test))
                raise InternalException(7, msg)
        result.append(value)
    return tuple(result)
