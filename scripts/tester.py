#!/usr/bin/env python3

import cmd as cmd__
import socket


class TestShell(cmd__.Cmd):
    intro = 'Welcome to the test shell. Type help or ? to list commands.\n'
    prompt = '~# '

    def __init__(self):
        super().__init__()
        self._ip = '127.0.0.1'
        self._port = 7999

    def _send(self, cmd: str):
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(3)
        print('Отправляю {}:{} \'{}\'...'.format(self._ip, self._port, cmd))
        try:
            client.connect((self._ip, self._port))
            client.send(cmd.encode() + b'\r\n')
        except (BrokenPipeError, ConnectionResetError, ConnectionRefusedError, OSError) as err:
            print('Ошибка подключения к {}:{}. {}: {}'.format(self._ip, self._port, err.errno, err.strerror))
        else:
            print('...Успех.')
        finally:
            client.close()

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

    def do_update(self, _):
        """Обновить терминал. Аргументы: нет"""
        self._send('rec:update_0_0')

    def do_rollback(self, _):
        """Откатывает последнее обновление. Аргументы: нет"""
        self._send('rec:rollback_0_0')

    def do_raw(self, arg):
        """Отправляет терминалу любые данные. Аргументы: что угодно"""
        if not arg:
            print('Вы забыли данные')
        else:
            self._send(arg)


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


if __name__ == '__main__':
    TestShell().cmdloop()
