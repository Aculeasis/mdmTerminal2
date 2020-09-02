#!/usr/bin/env python3

import os
import queue
import sys
import threading

import logger
import utils

ENTRYPOINT = 'Main'
NAME = 'NAME'
RELOAD = 'CFG_RELOAD'
PLUG_FILE = 'main.py'
API = 'API'
DISABLE_1 = 'DISABLE'
DISABLE_2 = 'disable'
TERMINAL_VER_MIN = 'TERMINAL_VER_MIN'
TERMINAL_VER_MAX = 'TERMINAL_VER_MAX'


class Plugins(threading.Thread):
    def __init__(self, cfg, log, owner):
        super().__init__(name='Plugins')
        self.cfg, self.log, self.own = cfg, log, owner
        self._queue = queue.Queue()
        self._target, self._lists, self._ignore = None, None, None
        self._init, self.modules, self._reloads = {}, {}, {}
        self._status = {
            'all': {},
            'deprecated': {},
            'broken': {}
        }

    @property
    def work(self):
        return self.is_alive()

    @work.setter
    def work(self, value):
        if not value:
            self._queue.put_nowait(None)

    def run(self):
        if not self.cfg.gt('plugins', 'enable'):
            return
        self.log('start.', logger.INFO)
        self.__start()

        while self.modules:
            cmd = self._queue.get()
            if cmd is None:
                break
            else:
                self._reload_all(cmd)

        self.__stop()

    def join(self, timeout=60):
        self.work = False
        super().join(timeout=timeout)

    def reload(self, diff: dict):
        if diff and self._reloads:
            self._queue.put_nowait(diff)

    def status(self, state: str) -> dict:
        return self._status.get(state, {})

    def __start(self):
        self._lists = {
            'to_black': set(),
            'black': set(utils.str_to_list(self.cfg.gt('plugins', 'blacklist'))),
            'white': set(utils.str_to_list(self.cfg.gt('plugins', 'whitelist'))),
            'on_failure': self.cfg.gt('plugins', 'blacklist_on_failure'),
        }
        self._ignore = {
            'black': set(),
            'white': set(),
        }

        self._init_all()
        self._start_all()
        self._update_blacklist()

        self._init.clear()
        self._target, self._lists, self._ignore = None, None, None

    def __stop(self):
        self._stop_all()
        for section in self._status.values():
            section.clear()
        self.modules.clear()
        self._reloads.clear()

    def _update_blacklist(self):
        self._lists['to_black'] -= self._lists['black']
        if not self._lists['to_black']:
            return
        to_blacklist = list(self._lists['to_black'])
        to_blacklist.sort()
        to_blacklist = ','.join(to_blacklist)
        blacklist = self.cfg.gt('plugins', 'blacklist')
        blacklist = '{},{}'.format(blacklist, to_blacklist) if blacklist else to_blacklist
        self.log('Add to blacklist: {}'.format(to_blacklist), logger.INFO)
        self.own.settings_from_inside({'plugins': {'blacklist': blacklist}})

    def _get_log(self, name: str):
        return self.log.add(name.capitalize())

    def _log(self, name, msg, lvl=logger.DEBUG):
        self.log.module(name.capitalize(), msg, lvl)

    def _init_all(self):
        oll = 0
        for plugin in os.listdir(self.cfg.path['plugins']):
            plugin_dir = os.path.join(self.cfg.path['plugins'], plugin)
            plugin_path = os.path.join(plugin_dir, PLUG_FILE)
            module_name = 'plugins.{}'.format(plugin)
            if not os.path.isfile(plugin_path):
                continue
            oll += 1
            self._target = None
            try:
                self._init_plugin(plugin_path, plugin_dir, module_name)
            except Exception as e:
                self.log('Error init {}: {}'.format(module_name, e), logger.ERROR)
                if self._target is not None:
                    if not (self._target in self._status['broken'] or self._target in self._status['deprecated']):
                        self._status['broken'][self._target] = plugin_dir
                    if self._lists['on_failure']:
                        self._lists['to_black'].add(self._target)
            if self._target is not None and self._target not in self._status['all']:
                self._status['all'][self._target] = plugin_dir

        for key, tail in (('white', 'not whitelisted'), ('black', 'blacklisted')):
            if self._ignore[key]:
                count = ' ' if len(self._ignore[key]) < 2 else ' [{}] '.format(len(self._ignore[key]))
                list_ = '\', \''.join(sorted(self._ignore[key]))
                self.log('Ignore{}\'{}\': {}'.format(count, list_, tail))
        if self._init:
            self.log('Init [{}/{}]: {}'.format(len(self._init), oll, ', '.join(key for key in self._init)))

    def _init_plugin(self, path: str, plugin_dir: str, module_name: str):
        module = import_module(path, module_name)
        if getattr(module, DISABLE_1, None):
            return

        for key in (NAME, ENTRYPOINT):
            val = getattr(module, key, None)
            if val is None:
                raise RuntimeError('\'{}\' missing or None'.format(key))
            if not val:
                raise RuntimeError('\'{}\' is empty'.format(key))

        name = getattr(module, NAME)
        if not isinstance(name, str):
            raise RuntimeError('\'{}\' must be str, not {}'.format(NAME, type(name)))
        if len(name) > 30:
            raise RuntimeError('Max \'{}\' length 30, get {}'.format(NAME, len(name)))
        if not name.islower() or name.isspace() or ',' in name:
            raise RuntimeError('\'{}\' must be lowered, without spaces and commas: \'{}\''.format(NAME, name))
        if name in self._init:
            raise RuntimeError('Plugin named \'{}\' already initialized'.format(name))

        if self._lists['white'] and name not in self._lists['white']:
            self._ignore['white'].add(name)
            return
        if name in self._lists['black']:
            self._ignore['black'].add(name)
            return
        self._target = name

        reload = getattr(module, RELOAD, None)
        if reload is not None and not is_iterable(reload):
            raise RuntimeError('\'{}\' must be iterable or None'.format(RELOAD))

        api = getattr(module, API, -1)
        if not isinstance(api, int):
            raise RuntimeError('\'{}\' present and not int: {}, {}'.format(API, repr(api), type(api)))

        if -1 < api < self.cfg.API:
            if name not in self._status['deprecated']:
                self._status['deprecated'][name] = plugin_dir
            msg = 'Plugin deprecated. Plugin api: {}, terminal api: {}. Ignore.'.format(api, self.cfg.API)
            self._log(name, msg, logger.WARN)
            return

        if not self._version_check(module, name):
            return

        self._init[name] = (getattr(module, ENTRYPOINT)(cfg=self.cfg, log=self._get_log(name), owner=self.own), reload)

    def _start_all(self):
        # special plugin
        plugin_updater = self._init.pop('plugin-updater', None)
        for name, (module, reload) in self._init.items():
            self._start_plugin(name, module, reload)
        if plugin_updater:
            self._start_plugin('plugin-updater', plugin_updater[0], plugin_updater[1])
        if self.modules:
            self.log('Load {} plugins.'.format(len(self.modules)))

    def _start_plugin(self, name: str, module, reload):
        if getattr(module, DISABLE_2, None):
            return
        try:
            module.start()
        except AttributeError:
            pass
        except Exception as e:
            self.log('Error start \'{}\': {}'.format(name, e), logger.ERROR)
            if name in self._status['all']:
                self._status['broken'][name] = self._status['all'][name]
            if self._lists['on_failure']:
                self._lists['to_black'].add(self._target)
            return
        self.modules[name] = module
        if reload and getattr(module, 'reload', None):
            self._reloads[name] = reload
        self._log(name, 'start.', logger.INFO)

    def _stop_all(self):
        for name, module in self.modules.items():
            try:
                self._stop_plugin(name, module)
            except Exception as e:
                self.log('Error stop \'{}\': {}'.format(name, e), logger.ERROR)

    def _stop_plugin(self, name: str, module):
        if getattr(module, 'join', None):
            self._log(name, 'stopping...')
            module.join()
        elif getattr(module, 'stop', None):
            module.stop()
        else:
            return
        self._log(name, 'stop.', logger.INFO)

    def _reload_all(self, diff: dict):
        for name in [key for key in self._reloads]:
            if is_intersection(self._reloads[name], diff):
                try:
                    self._reload(name)
                except Exception as e:
                    self.log('Error reload \'{}\': {}'.format(name, e), logger.ERROR)
                    del self._reloads[name]

    def _reload(self, name: str):
        self.modules[name].reload()
        self._log(name, 'reload.', logger.INFO)

    def _version_check(self, module, name : str) -> bool:
        def str_ver(_ver: tuple) -> str:
            return '.'.join(map(str, _ver))

        def correct_ver(_ver) -> bool:
            return isinstance(_ver, tuple) and len(_ver) == 3 and all([isinstance(x, int) for x in _ver])

        ver_min, ver_max = getattr(module, TERMINAL_VER_MIN, None), getattr(module, TERMINAL_VER_MAX, None)
        if ver_min:
            if not correct_ver(ver_min):
                self._log(name, 'Wrong {} - ignore'.format(TERMINAL_VER_MIN))
            elif ver_min > self.cfg.version_info:
                msg = 'Terminal too old, plugin disabled (min {}, current {})'.format(
                    str_ver(ver_min), self.cfg.version_str)
                self._log(name, msg, logger.WARN)
                return False
        if ver_max:
            if not correct_ver(ver_max):
                self._log(name, 'Wrong {} - ignore'.format(TERMINAL_VER_MAX))
            elif ver_max < self.cfg.version_info:
                msg = 'Terminal too new, plugin disabled (max {}, current {})'.format(
                    str_ver(ver_max), self.cfg.version_str)
                self._log(name, msg, logger.WARN)
                return False
        return True


def import_module(path: str, module_name: str):
    sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
    try:
        if sys.version_info >= (3, 5):
            import importlib.util
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        else:
            from importlib.machinery import SourceFileLoader
            module = SourceFileLoader(module_name, path).load_module()
    finally:
        sys.path.pop(0)
    return module


def is_iterable(iterable) -> bool:
    try:
        _ = iter(iterable)
    except TypeError:
        return False
    return True


def is_intersection(iterable, diff: dict) -> bool:
    if not (diff and isinstance(diff, dict)):
        return False
    for key in iterable:
        if key in diff:
            if isinstance(iterable, dict) and iterable[key] and is_iterable(iterable[key]):
                if is_intersection(iterable[key], diff[key]):
                    return True
            else:
                return True
    return False
