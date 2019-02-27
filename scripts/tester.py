#!/usr/bin/env python3

import base64
import cmd as cmd__
import hashlib
import json
import socket
import time

ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionRefusedError, OSError)
CRLF = b'\r\n'


class TestShell(cmd__.Cmd):
    intro = 'Welcome to the test shell. Type help or ? to list commands.\n'
    prompt = '~# '

    def __init__(self):
        super().__init__()
        self._ip = '127.0.0.1'
        self._port = 7999
        self._token = ''

    def _send(self, cmd: str, is_logger=False, is_duplex=False, auth=None):
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(10 if not (is_logger or is_duplex) else None)
        cmd = '\r\n'.join(cmd.replace('\\n', '\n').split('\n')).encode() + (CRLF*2 if not is_duplex else CRLF)
        print('Отправляю {}:{} {}...'.format(self._ip, self._port, repr(cmd)))
        if self._token:
            cmd = b'authorization:' + hashlib.sha3_512(self._token.encode()).hexdigest().encode() + CRLF + cmd
        try:
            client.connect((self._ip, self._port))
            client.send(cmd)
        except ERRORS as err:
            print('Ошибка подключения к {}:{}. {}: {}'.format(self._ip, self._port, err.errno, err.strerror))
        else:
            print('...Успех.')
            data = b''
            stage = 0
            while True:
                try:
                    chunk = client.recv(1024)
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
                    if is_logger:
                        print(line)
                        continue
                    if is_duplex and auth:
                        stage = self.handshake(line, stage)
                        if not stage:
                            auth = None
                        if stage < 0:
                            return
                        continue
                    if line.startswith('{') and line.endswith('}'):
                        # json? json!
                        result = self._parse_json(line)
                        if result:
                            client.send(result.encode() + CRLF)
                        continue
                    if line.startswith('pong:'):
                        try:
                            diff = time.time() - float(line.split(':', 1)[1])
                        except (ValueError, TypeError):
                            pass
                        else:
                            line = 'ping {} ms'.format(int(diff * 1000))
                    print('Ответ: {}'.format(line))
        finally:
            client.close()

    @staticmethod
    def handshake(line: str, stage: int):
        if line == 'upgrade duplex ok':
            return 0
        else:
            try:
                data = json.loads(line)
                if not isinstance(data, dict):
                    raise TypeError('Data must be dict type')
            except (json.decoder.JSONDecodeError, TypeError, ValueError) as e:
                print('Ошибка декодирования: {}'.format(e))
                return -1
            print('Reply: {}'.format(repr(data)))
            return -1 if data.get('code', -1) else stage

    @staticmethod
    def _parse_json(data: str):
        try:
            data = json.loads(data)
            if not isinstance(data, dict):
                raise TypeError('Data must be dict type')
        except (json.decoder.JSONDecodeError, TypeError) as e:
            return print('Ошибка декодирования: {}'.format(e))

        for key in ('cmd', 'code'):
            if key not in data:
                return print('Не хватает ключа: {}'.format(key))

        if data['code'] != 0:
            print('Терминал сообщил об ошибке {} [{}]: {}'.format(data['cmd'], data['code'], data.get('msg', '')))
            return

        if 'body' not in data:
            if 'msg' in data:
                return print('{}: {}'.format(data['cmd'], data['msg']))
            return print('Не хватает ключа: body')
        if data['cmd'] == 'recv_model':
            if 'filename' not in data:
                return print('Не хватает ключа: filename')
            try:
                file_size = len(base64_to_bytes(data['body']))
            except RuntimeError as e:
                return print('Ошибка декодирования body: {}'.format(e))
            optional = ', '.join(['{}={}'.format(k, repr(data[k])) for k in ('username', 'phrase') if k in data])
            result = 'Получен файл {}; данные: {}; размер {} байт'.format(data['filename'], optional, file_size)
        elif data['cmd'] == 'list_models':
            if not isinstance(data['body'], dict) or \
                    len([k for k in ('models', 'allow') if isinstance(data['body'].get(k, ''), list)]) < 2:
                return print('Недопустимое body: {}'.format(repr(data.get('body'))))
            result = 'Все модели: {}; разрешенные: {}'.format(
                ', '.join(data['body']['models']), ', '.join(data['body']['allow'])
            )
        elif data['cmd'] == 'cmd':
            print('cmd: {}'.format(repr(data['body'])))
            return 'tts:{}'.format(data['body']['qry'])
        elif data['cmd'] == 'api':
            return print('api: {}'.format(repr(data['body'])))
        elif data['cmd'] == 'info':
            for key in ('cmd', 'msg'):
                if key not in data['body']:
                    return print('Не хватает ключа в body: {}'.format(key))
            if isinstance(data['body']['cmd'], (list, dict)):
                data['body']['cmd'] = ', '.join(x for x in data['body']['cmd'])
            if isinstance(data['body']['msg'], str) and '\n' in data['body']['msg']:
                data['body']['msg'] = '\n' + data['body']['msg']
            print('\nINFO: {}'.format(data['body']['cmd']))
            print('MSG: {}\n'.format(data['body']['msg']))
            return
        else:
            result = 'Неизвестная команда: {}'.format(repr(data['cmd']))
        print('Ответ на {}: {}'.format(repr(data['cmd']), result))

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
        """Отправляет фразу терминалу. Аргументы: фраза"""
        if not arg:
            print('Добавьте фразу')
        else:
            self._send('tts:' + arg)

    def do_ask(self, arg):
        """Отправляет ask терминалу. Аргументы: фраза"""
        if not arg:
            print('Добавьте фразу')
        else:
            self._send('ask:' + arg)

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
        self._send('ping:{}'.format(time.time()))

    def do_list_models(self, _):
        """Список моделей. Аргументы: нет"""
        self._send('list_models')

    def do_recv_model(self, filename):
        """Запросить модель у терминала. Аргументы: имя файла"""
        self._send('recv_model:{}'.format(filename))

    def do_log(self, _):
        """Подключает удаленного логгера к терминалу. Аргументы: нет"""
        self._send('remote_log', is_logger=True)

    def do_duplex(self, _):
        """Один сокет для всего."""
        self._send('upgrade duplex', is_duplex=True, auth=True)

    def do_raw(self, arg):
        """Отправляет терминалу любые данные. Аргументы: что угодно"""
        if not arg:
            print('Вы забыли данные')
        else:
            self._send(arg)

    def do_token(self, token: str):
        """Задать токен для авторизации. Аргументы: токен"""
        self._token = token


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


if __name__ == '__main__':
    TestShell().cmdloop()
