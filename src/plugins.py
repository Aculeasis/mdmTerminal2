#!/usr/bin/env python3

import os
import sys
import threading

import logger

ENTRYPOINT = 'Main'
NAME = 'NAME'
RELOAD = 'CFG_RELOAD'
PLUG_FILE = 'main.py'
DISABLE_1 = 'DISABLE'
DISABLE_2 = 'disable'


class Plugins:
    def __init__(self, cfg, log, owner):
        self.cfg = cfg
        (self.log, self._m_log) = log
        self.own = owner
        self._lock = threading.Lock()
        self._init = {}
        self._modules = {}
        self._reloads = {}

    def start(self):
        with self._lock:
            self.log('start.', logger.INFO)
            self._init_all()
            self._start_all()

    def stop(self):
        with self._lock:
            self._stop_all()
            self._modules, self._reloads = {}, {}
            self.log('stop.', logger.INFO)

    def reload(self, diff: dict):
        with self._lock:
            self._reload_all(diff)

    def _get_log(self, name: str):
        name = name.capitalize()
        return lambda msg, lvl=logger.DEBUG: self._m_log(name, msg, lvl)

    def _log(self, name, msg, lvl=logger.DEBUG):
        self._m_log(name.capitalize(), msg, lvl)

    def _init_all(self):
        for plugin in os.listdir(self.cfg.path['plugins']):
            plugin_path = os.path.join(self.cfg.path['plugins'], plugin, PLUG_FILE)
            module_name = 'plugins.{}'.format(plugin)
            if not os.path.isfile(plugin_path):
                continue
            try:
                self._init_plugin(plugin_path, module_name)
            except Exception as e:
                self.log('Error init {}: {}'.format(module_name, e), logger.ERROR)
        if self._init:
            self.log('Init {}'.format(', '.join(key for key in self._init)))

    def _init_plugin(self, path: str, module_name: str):
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
        if not name.islower() or name.isspace():
            raise RuntimeError('\'{}\' must be lowered and without space: \'{}\''.format(NAME, name))
        if name in self._init:
            raise RuntimeError('Plugin \'{}\' already initialized'.format(name))

        reload = getattr(module, RELOAD, None)
        if reload is not None and not is_iterable(reload):
            raise RuntimeError('\'{}\' must be iterable or None'.format(RELOAD))

        self._init[name] = (getattr(module, ENTRYPOINT)(cfg=self.cfg, log=self._get_log(name), owner=self.own), reload)

    def _start_all(self):
        for name, (module, reload) in self._init.items():
            if getattr(module, DISABLE_2, None):
                continue
            try:
                self._start_plugin(name, module)
            except Exception as e:
                self.log('Error star \'{}\': {}'.format(name, e), logger.ERROR)
                continue
            self._modules[name] = module
            if reload and getattr(module, 'reload', None):
                self._reloads[name] = reload
        self._init = {}

    def _start_plugin(self, name: str, module):
        try:
            module.start()
        except AttributeError:
            return
        self._log(name, 'start.', logger.INFO)

    def _stop_all(self):
        for name, module in self._modules.items():
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
        self._modules[name].reload()
        self._log(name, 'reload.', logger.INFO)


def import_module(path: str, module_name: str):
    if sys.version_info >= (3, 5):
        import importlib.util
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        from importlib.machinery import SourceFileLoader
        module = SourceFileLoader(module_name, path).load_module()
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
