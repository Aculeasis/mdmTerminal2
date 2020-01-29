#!/usr/bin/env python3

import os
import sys
import threading
import time

import logger
from languages import F
from owner import Owner
from utils import Popen


class Updater(threading.Thread):
    CFG = 'update'

    def __init__(self, cfg, log, owner: Owner):
        super().__init__(name='Updater')
        self._cfg = cfg
        self.log = log
        self.own = owner

        self._old_hash = None
        self._last = self._load_cfg()
        self.work = False
        self._sleep = threading.Event()
        self._action = None

        self._notify_update = self.own.registration('updater')

    def start(self):
        if self._cfg.platform != 'Linux':
            self.log('don\'t support this system: {}'.format(self._cfg.platform), logger.WARN)
            return
        self.work = True
        super().start()
        self.log('start', logger.INFO)

    def join(self, timeout=30):
        self._sleep.set()
        super().join(timeout=timeout)

    def update(self):
        self._action = 'update'
        self._sleep.set()

    def manual_rollback(self):
        self._action = 'rollback'
        self._sleep.set()

    def _manual_rollback(self):
        up = self._new_worker()
        msg = self._fallback(up, self._last['hash'], 'rollback')
        if msg == F('Выполнен откат.') and self._may_restart():
            self.own.die_in(7)
        self.own.terminal_call('tts', msg)

    def run(self):
        while self.work:
            to_sleep = self._to_sleep()
            self._sleep.wait(to_sleep)
            if not self.work:
                break
            if self._sleep.is_set():
                self._sleep.clear()
                if self._action == 'update':
                    self._check_update()
                elif self._action == 'rollback':
                    self._manual_rollback()
                self._action = None
            elif to_sleep:
                self._check_update(False)

    def _to_sleep(self):
        interval = self._cfg.gt('update', 'interval')
        if interval <= 0:
            self._sleep.wait(3600)
            return 0
        interval *= 24 * 3600
        diff = int(time.time()) - self._last['check']
        if diff >= interval:
            return 10
        if diff < 0:
            # Часы слетели. Что же делать?
            return 10 * 60
        return interval - diff

    def _check_update(self, say=True):
        self._old_hash = None
        msg = self._update()
        self._last['check'] = int(time.time())
        self._last['hash'] = self._old_hash or self._last['hash']
        self._save_cfg()
        if msg and say:
            self.own.terminal_call('tts', msg)

    def _save_cfg(self):
        self._cfg.save_dict(self.CFG, self._last)

    def _load_cfg(self) -> dict:
        cfg = self._cfg.load_dict(self.CFG) or {}
        return {'hash': cfg.get('hash'), 'check': cfg.get('check', 0)}

    def _update(self):
        up = self._new_worker()

        try:
            up.pull()
        except RuntimeError as e:
            self._notify_update('pull_failed')
            self.log('{}: {}'.format(F('Во время обновления возникла ошибка'), e), logger.CRIT)
            return '{}.'.format(F('Во время обновления возникла ошибка'))

        try:
            up.check_pull()
        except RuntimeError as e:
            self._notify_update('check_pull_failed')
            return self._auto_fallback(up, e)

        if not up.updated():
            self._notify_update('update_nope')
            self.log(F('Вы используете последнюю версию терминала.'), logger.INFO)
            return F('Вы используете последнюю версию терминала.')
        new_files = up.new_files()
        if new_files:
            self.log(F('Файлы обновлены: {}', new_files), logger.DEBUG)

        try:
            self._up_dependency('apt', up.update_apt)
        except RuntimeError as e:
            self._notify_update('apt_failed')
            return self._auto_fallback(up, e)
        try:
            self._up_dependency('pip', up.update_pip)
        except RuntimeError as e:
            self._notify_update('pip_failed')
            return self._auto_fallback(up, e)

        self._notify_update('update_yes')
        self.log(F('Терминал успешно обновлен.'), logger.INFO)
        self._old_hash = up.get_old_hash()
        if self._may_restart() and new_files:
            self.own.die_in(7)
            msg = F('Терминал успешно обновлен.')
        else:
            msg = '{} {}'.format(F('Терминал успешно обновлен.'), F('Требуется перезапуск.'))
        return msg

    def _may_restart(self):
        if self._cfg.gt('update', 'turnoff') < 0:
            if not sys.stdin.isatty():
                return True
        elif self._cfg.gt('update', 'turnoff'):
            return True
        return False

    def _auto_fallback(self, up, error):
        msg = F('Во время обработки обновления или установки зависимостей возникла ошибка')
        self.log('{}: {}'.format(msg, error), logger.ERROR)
        if self._cfg.gt('update', 'fallback'):
            return '{}. {}'.format(msg, self._fallback(up))
        return '{}.'.format(msg)

    def _fallback(self, up, hash_=None, mode='fallback'):
        self.log(F('Выполняется откат обновления.'), logger.DEBUG)
        try:
            if hash_:
                up.set_old_hash(hash_)
            up.fallback()
        except RuntimeError as e:
            self._notify_update('{}_failed'.format(mode))
            self.log(F('Во время отката обновления возникла ошибка: {}', e), logger.CRIT)
            return F('Откат невозможен.')
        else:
            self._notify_update('{}_ok'.format(mode))
            self.log(F('Откат обновления выполнен успешно.'), logger.INFO)
            return F('Выполнен откат.')

    def _up_dependency(self, name: str, updater):
        to_update = self._cfg.gt('update', name)
        packages = updater(to_update)
        if packages:
            msg = F('Зависимости {} {}обновлены: {}').format(name, '' if to_update else F('не '), packages)
            event = '{}_{}'.format(name, 'yes' if to_update else 'no')
            self._notify_update(event)
            self.log(msg, logger.DEBUG if to_update else logger.WARN)

    def _new_worker(self):
        return Worker(os.path.split(self._cfg.path['home'])[0], sys.executable)


def l_split(path: str) -> list:
    data = path.split(os.path.sep, 1)
    return data if len(data) == 2 else ['', '']


def is_commit_hash(commit_hash):
    if not isinstance(commit_hash, str):
        return False
    return len(commit_hash) == 40


class Worker:
    APT_UPDATE = ['apt-get', 'update', '-qq']
    APT_INSTALL = ['apt-get', 'install', '-y', '-qq']
    PIP_FILE = os.path.join('Requirements', 'pip-requirements.txt')
    APT_FILE = os.path.join('Requirements', 'system-requirements.txt')

    def __init__(self, home_path, python_path):
        self.PIP_INSTALL = [python_path, '-m', 'pip', 'install', '-U', '-q']
        self._home = home_path
        self._new_pip = []
        self._new_apt = []
        self._new_files = []
        self._old_hash = None
        self._new_hash = None

    def updated(self):
        return self._new_files or self._new_pip or self._new_apt

    def update_pip(self, upgrade: bool):
        if upgrade and self._new_pip:
            Popen(self.PIP_INSTALL + self._new_pip).run()
        return ', '.join(self._new_pip)

    def update_apt(self, upgrade: bool):
        if upgrade and self._new_apt:
            Popen(self.APT_UPDATE).run()
            Popen(self.APT_INSTALL + self._new_apt).run()
        return ', '.join(self._new_apt)

    def new_files(self):
        return ', '.join(self._new_files)

    def fallback(self):
        if is_commit_hash(self._old_hash):
            self._git(['reset', '--hard', self._old_hash])
        else:
            raise RuntimeError('Rollback impossible, wrong hash: {}'.format(repr(self._old_hash)))

    def set_old_hash(self, old_hash: str or None):
        current_hash = self._get_hash()
        if not is_commit_hash(old_hash):
            raise RuntimeError('Wrong hash: {}'.format(repr(old_hash)))
        if current_hash == old_hash:
            raise RuntimeError('This is current hash: {}'.format(repr(old_hash)))
        self._old_hash = old_hash

    def get_old_hash(self):
        return self._old_hash if self._old_hash != self._new_hash else None

    def pull(self):
        self._old_hash = self._get_hash()
        self._git(['pull'])
        self._new_hash = self._get_hash()

    def check_pull(self):
        if self._old_hash != self._new_hash and self._new_hash:
            self._fill_lists()

    def _fill_lists(self):
        for file in self._git(['diff', '-z', '--name-only', self._old_hash, self._new_hash]).strip('\n\0').split('\0'):
            if file == self.PIP_FILE:
                self._new_pip = self._get_new_packages(self.PIP_FILE)
            elif file == self.APT_FILE:
                self._new_apt = self._get_new_packages(self.APT_FILE)
            else:
                a, b = l_split(file)
                if a == 'src' and b.endswith('.py') and len(b) > 3:
                    self._new_files.append(b)

    def _get_new_packages(self, path):
        data = []
        ignore = set()
        for line in self._git(['diff', '-z', '-U0', self._old_hash, self._new_hash, path]).split('\n'):
            line = line.strip('\n').strip('\r').strip(' ')
            if line.startswith('+'):
                ignore_line = False
            elif line.startswith('-'):
                ignore_line = True
            else:
                continue
            line = line[1:]
            for test in (' ', '#', '\\'):
                if test in line:
                    line = ''
                    break
            if line:
                if ignore_line:
                    ignore.add(line)
                else:
                    data.append(line)
        return [packet for packet in data if packet not in ignore]

    def _get_hash(self):
        data = self._git(['log', '-n', '1'])
        hash_ = data.split('\n')[0].split(' ')[-1]
        if not is_commit_hash(hash_):
            raise RuntimeError('Error getting hash from git: {}'.format(repr(data)))
        return hash_

    def _git(self, cmd: list):
        return Popen(['git', '-C', self._home] + cmd).run()
