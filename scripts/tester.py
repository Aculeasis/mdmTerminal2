#!/usr/bin/env python3

import base64
import cmd as cmd__
import hashlib
import json
import socket
import time
from threading import Thread, Lock

ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionRefusedError, OSError)
CRLF = b'\r\n'


class Client:
    def __init__(self, address: tuple, token, chunk_size=1024, threading=False, is_logger=False, api=True):
        self.chunk_size = chunk_size
        self.work, self.connect = False, False
        self.address = address
        self.is_logger = is_logger
        self.api = api
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client.settimeout(10 if not (is_logger or threading) else None)
        self.token = token
        self.thread = Thread(target=self._run) if threading else None
        self._lock = Lock()
        try:
            self.client.connect(address)
        except ERRORS as err:
            print('Ошибка подключения к {}:{}. {}: {}'.format(*address, err.errno, err.strerror))
        else:
            self.connect = True
            print('Подключено к {}:{}'.format(*address))
        if self.connect and self.thread:
            self.work = True
            self.thread.start()
        if self.connect:
            self._auth()

    def _run(self):
        try:
            self._read_loop()
        finally:
            print('Отключено от {}:{}'.format(*self.address))
            self.work = False
            self.connect = False
            self.client.close()

    def _auth(self):
        if self.token:
            cmd = json.dumps({
                'method': 'authorization',
                'params': [hashlib.sha512(self.token.encode()).hexdigest()],
                'id': 'authorization',
            }).encode()
            self._send(cmd)

    def send(self, cmd):
        self._send('\r\n'.join(cmd.replace('\\n', '\n').split('\n')).encode() + (CRLF if not self.thread else b''))
        if self.connect and not self.thread:
            self._run()

    def _send(self, data: bytes):
        if not self.connect:
            return
        try:
            with self._lock:
                self.client.send(data + CRLF)
        except ERRORS as e:
            print('Write error {}:{}:{}'.format(*self.address, e))
            self.connect = False

    def _read_loop(self):
        data = b''
        stage = 1
        while self.connect:
            try:
                chunk = self.client.recv(self.chunk_size)
            except ERRORS:
                break
            if not chunk:
                break
            data += chunk
            while CRLF in data:
                line, data = data.split(CRLF, 1)
                if not line:
                    return
                line = line.decode()
                if self.is_logger:
                    print(line)
                    continue
                if self.thread and self.token and stage:
                    stage = self._handshake(line, stage)
                    if stage < 0:
                        return
                    continue
                if line.startswith('{') and line.endswith('}'):
                    # json? json!
                    result = parse_json(line, self.api)
                    if result:
                        self._send(result.encode())
                    continue
                print('Ответ: {}'.format(line))

    def _handshake(self, line: str, stage: int):
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                raise TypeError('Data must be dict type')
        except (json.decoder.JSONDecodeError, TypeError, ValueError) as e:
            print('Ошибка декодирования: {}'.format(e))
            return -1
        if 'result' in data and data.get('id') == 'upgrade duplex':
            self._send(
                json.dumps({'method': 'subscribe', 'params': ['cmd', 'talking', 'record']}, ensure_ascii=False).encode()
            )
            return 0
        return stage

    def stop(self):
        if self.thread and self.work:
            self.work = False
            self.connect = False
            self.client.shutdown(socket.SHUT_RD)
            self.client.close()
            self.thread.join(10)


class TestShell(cmd__.Cmd):
    intro = 'Welcome to the test shell. Type help or ? to list commands.\n'
    prompt = '~# '

    def __init__(self):
        super().__init__()
        self._ip = '127.0.0.1'
        self._port = 7999
        self._token = ''
        self.chunk_size = 1024
        self._client = None
        self._api = True

    def __del__(self):
        self._duplex_off()

    def _send_json(self, cmd: str, data='', is_logger=False):
        self._send(json.dumps({'method': cmd, 'params': [data], 'id': cmd}, ensure_ascii=False), is_logger)

    def _send_true_json(self, cmd: str, data: dict):
        self._send(json.dumps({'method': cmd, 'params': data, 'id': cmd}, ensure_ascii=False))

    def _send(self, cmd: str, is_logger=False):
        if self._client:
            if not self._client.connect or is_logger:
                self._duplex_off()
            else:
                self._client.send(cmd)
        else:
            client = Client((self._ip, self._port), self._token, self.chunk_size, is_logger=is_logger, api=self._api)
            client.send(cmd)

    def _duplex_off(self):
        if self._client:
            self._client.stop()
            self._client = None
            print('Stop duplex')

    def _duplex(self):
        if self._client:
            self._duplex_off()
        else:
            print('Start duplex')
            self._client = Client((self._ip, self._port), self._token, self.chunk_size, True, api=self._api)

    def _send_says(self, cmd: str, data: str):
        test = data.rsplit('~', 1)
        if len(test) == 2 and len(test[1]) > 3:
            self._send_true_json(cmd, {'text': test[0], 'provider': test[1]})
        else:
            self._send(cmd + ':' + data)

    def do_connect(self, arg):
        """Проверяет подключение к терминалу и позволяет задать его адрес. Аргументы: IP:PORT"""
        if arg:
            cmd = arg.split(':')
            if len(cmd) != 2:
                cmd = arg.split(' ')
            if len(cmd) > 2:
                return print('Ошибка парсинга. Аргументы: IP:PORT or IP or PORT')
            if len(cmd) == 1:
                cmd = cmd[0]
                if cmd.isdigit():
                    cmd = [self._ip, cmd]
                else:
                    cmd = [cmd, self._port]
            try:
                self._port = int(cmd[1])
            except ValueError:
                return print('Ошибка парсинга - порт не число: {}'.format(cmd[1]))
            self._ip = cmd[0]
        self._duplex_off()
        self._send('pause:')

    @staticmethod
    def do_exit(_):
        """Выход из оболочки"""
        print('Выход.')
        return True

    def do_voice(self, _):
        """Отправляет voice:."""
        self._send('voice:')

    def do_tts(self, arg):
        """Отправляет фразу терминалу. Аргументы: фраза или фраза~провайдер"""
        if not arg:
            print('Добавьте фразу')
        else:
            self._send_says('tts', arg)

    def do_ttss(self, arg):
        """Отправляет фразы терминалу. Аргументы: фразы"""
        if not arg:
            print('Добавьте фразы')
        else:
            result = [{'method': 'tts', 'params': {'text': text}} for text in arg.split(' ')]
            self._send(json.dumps(result, ensure_ascii=False))

    def do_ask(self, arg):
        """Отправляет ask терминалу. Аргументы: фраза или фраза~провайдер"""
        if not arg:
            print('Добавьте фразу')
        else:
            self._send_says('ask', arg)

    def do_api(self, _):
        """Отключить/включить показ уведомлений, для duplex mode"""
        self._api = not self._api
        if self._client:
            self._client.api = self._api
        print('Уведомления {}.'.format('включены' if self._api else 'отключены'))

    def do_pause(self, _):
        """Отправляет pause:."""
        self._send('pause:')

    def do_save(self, _):
        """Отправляет команду на перезагрузку"""
        self._send('rec:save_1_1')

    def do_record(self, arg):
        """Запись образца для фразы. Аргументы: [Номер фразы (1-6)] [Номер образца (1-3)]"""
        cmd = get_params(arg, '[Номер фразы (1-6)] [Номер образца (1-3)]')
        if not cmd or not num_check(cmd):
            return
        self._send('rec:rec_{}_{}'.format(*cmd))

    def do_play(self, arg):
        """Воспроизводит записанный образец. Аргументы: [Номер фразы (1-6)] [Номер образца (1-3)]"""
        cmd = get_params(arg, '[Номер фразы (1-6)] [Номер образца (1-3)]')
        if not cmd or not num_check(cmd):
            return
        self._send('rec:play_{}_{}'.format(*cmd))

    def do_compile(self, arg):
        """Компилирует фразу. Аргументы: [Номер фразы (1-6)]"""
        cmd = get_params(arg, '[Номер фразы (1-6)]', count=1)
        if not cmd:
            return
        cmd = cmd[0]
        if num_check([cmd, 1]):
            self._send('rec:compile_{0}_{0}'.format(cmd))

    def do_del(self, arg):
        """Удаляет модель. Аргументы: [Номер модели (1-6)]"""
        cmd = get_params(arg, '[Номер модели (1-6)]', count=1)
        if not cmd:
            return
        cmd = cmd[0]
        if num_check([cmd, 1]):
            self._send('rec:del_{0}_{0}'.format(cmd))

    def do_update(self, _):
        """Обновить терминал. Аргументы: нет"""
        self._send('rec:update_0_0')

    def do_rollback(self, _):
        """Откатывает последнее обновление. Аргументы: нет"""
        self._send('rec:rollback_0_0')

    def do_ping(self, _):
        """Пинг. Аргументы: нет"""
        self._send_json('ping', str(time.time()))

    def do_list_models(self, _):
        """Список моделей. Аргументы: нет"""
        self._send_json('list_models')

    def do_recv_model(self, filename):
        """Запросить модель у терминала. Аргументы: имя файла"""
        self.chunk_size = 1024 * 1024
        self._send_json('recv_model', filename)

    def do_log(self, _):
        """Подключает удаленного логгера к терминалу. Аргументы: нет"""
        self._send('remote_log', is_logger=True)

    def do_duplex(self, _):
        """Один сокет для всего. Включает и выключает"""
        self._duplex()
        if self._client:
            self._send_json('upgrade duplex')

    def do_raw(self, arg):
        """Отправляет терминалу любые данные. Аргументы: что угодно"""
        if not arg:
            print('Вы забыли данные')
        else:
            self._send(arg)

    def do_token(self, token: str):
        """Задать токен для авторизации. Аргументы: токен"""
        self._token = token

    def do_test_record(self, arg):
        """[filename] [phrase_time_limit]"""
        arg = arg.rsplit(' ', 1)
        if not arg[0]:
            print('Use [filename] [phrase_time_limit](optional)')
            return
        data = {'file': arg[0]}
        if len(arg) == 2:
            try:
                data['limit'] = float(arg[1])
            except ValueError as e:
                print('limit must be numeric: {}'.format(e))
                return
        self._send_true_json('test.record', data=data)

    def do_test_play(self, arg):
        """[file1,file2..fileN]"""
        self._send_true_json('test.play', data={'files': str_to_list(arg)})

    def do_test_delete(self, arg):
        """[file1,file2..fileN]"""
        self._send_true_json('test.delete', data={'files': str_to_list(arg)})

    def do_test_test(self, arg):
        """[provider1,provider2..providerN] [file1,file2..fileN]"""
        cmd = get_params(arg, '[provider1,provider2..providerN] [file1,file2..fileN]', to_type=None)
        if not cmd:
            return
        self._send_true_json('test.test', data={'providers': str_to_list(cmd[0]), 'files': str_to_list(cmd[1])})

    def do_test_list(self, _):
        self._send_true_json('test.list', data={})

    def do_info(self, arg):
        """Информация о команде"""
        self._send_json('info', data=arg)


def str_to_list(line) -> list:
    return [el.strip() for el in line.split(',')]


def num_check(cmd):
    if 6 <= cmd[0] <= 1:
        print('Номер фразы 1-6, не {}'.format(cmd[0]))
        return False
    if 3 <= cmd[1] <= 1:
        print('Номер образца 1-3, не {}'.format(cmd[1]))
        return False
    return True


def get_params(arg, helps, seps=None, to_type=int or None, count=2):
    def err():
        return print('Ошибка парсинга \'{}\'. Используйте: {}'.format(arg, helps))
    seps = seps or [' ']
    for sep in seps:
        cmd = arg.split(sep)
        if len(cmd) == count:
            if to_type is not None:
                try:
                    cmd = [to_type(test) for test in cmd]
                except ValueError:
                    return err()
            return cmd
    return err()


def base64_to_bytes(data):
    try:
        return base64.b64decode(data)
    except (ValueError, TypeError) as e:
        raise RuntimeError(e)


def parse_dict(cmd, data):
    if cmd == 'recv_model':
        for key in ('filename', 'data'):
            if key not in data:
                return print('Не хватает ключа: {}'.format(key))
        try:
            file_size = len(base64_to_bytes(data['data']))
        except RuntimeError as e:
            return print('Ошибка декодирования data: {}'.format(e))

        optional = ', '.join(['{}={}'.format(k, repr(data[k])) for k in ('username', 'phrase') if k in data])
        result = 'Получен файл {}; данные: {}; размер {} байт'.format(data['filename'], optional, file_size)
    elif cmd == 'list_models':
        if len([k for k in ('models', 'allow') if isinstance(data.get(k, ''), list)]) < 2:
            return print('Недопустимое body: {}'.format(repr(data)))
        result = 'Все модели: {}; разрешенные: {}'.format(
            ', '.join(data['models']), ', '.join(data['allow'])
        )
    elif cmd == 'info':
        for key in ('cmd', 'msg'):
            if key not in data:
                return print('Не хватает ключа в body: {}'.format(key))
        flags = None
        if isinstance(data['cmd'], (list, dict)):
            data['cmd'] = ', '.join(x for x in data['cmd'])
        if isinstance(data['msg'], str) and '\n' in data['msg']:
            data['msg'] = '\n' + data['msg']
        if isinstance(data.get('flags'), list) and data['flags']:
            flags = ', '.join(data['flags'])

        print('\nINFO: {}'.format(data['cmd']))
        print('MSG: {}\n'.format(data['msg']))
        if flags:
            print('FLAGS: {}\n'.format(flags))
        return
    else:
        return cmd, data
    return result


def parse_str(cmd, data):
    if cmd == 'ping':
        try:
            diff = time.time() - float(data)
        except (ValueError, TypeError):
            pass
        else:
            print('ping {} ms'.format(int(diff * 1000)))
            return
    return cmd, data


def parse_json(data: str, api):
    try:
        data = json.loads(data)
        if not isinstance(data, dict):
            raise TypeError('Data must be dict type')
    except (json.decoder.JSONDecodeError, TypeError) as e:
        return print('Ошибка декодирования: {}'.format(e))

    if 'error' in data:
        result = (data.get('id', 'null'), data['error'].get('code'), data['error'].get('message'))
        print('Терминал сообщил об ошибке {} [{}]: {}'.format(*result))
        return
    if 'method' in data:
        if isinstance(data['method'], str) and data['method'].startswith('notify.') and api:
            notify = data['method'].split('.', 1)[1]
            info = data.get('params')
            if isinstance(info, dict):
                args = info.get('args')
                kwargs = info.get('kwargs')
                if isinstance(args, list) and len(args) == 1 and not kwargs:
                    info = args[0]
                    if isinstance(info, bool):
                        info = 'ON' if info else 'OFF'
                elif isinstance(kwargs, dict) and not args:
                    info = kwargs
            print('Уведомление: {}: {}'.format(notify, info))
            if notify == 'cmd':
                tts = data.get('params', {}).get('kwargs', {}).get('qry', '')
                if tts:
                    return json.dumps({'method': 'tts', 'params': {'text': tts}}, ensure_ascii=False)
        return
    cmd = data.get('id')
    data = data.get('result')
    if isinstance(data, dict):
        result = parse_dict(cmd, data)
    elif isinstance(data, str):
        result = parse_str(cmd, data)
    else:
        result = data if data is not None else 'null'
    if result is not None:
        line = 'Ответ на {}: {}'.format(repr(cmd), result)
        if cmd == 'ping':
            line = parse_ping(result) or line
        print(line)


def parse_ping(data):
    try:
        diff = time.time() - float(data[0])
    except (ValueError, TypeError, IndexError):
        return None
    else:
        return 'ping {} ms'.format(int(diff * 1000))


if __name__ == '__main__':
    TestShell().cmdloop()
