#!/usr/bin/env python3

import os
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


class Plugins:
    def __init__(self, cfg, log, owner):
        self.cfg = cfg
        self.log = log
        self.own = owner
        self._lock = threading.Lock()
        self._target = None
        self._to_blacklist, self._blacklist, self._whitelist = None, None, None
        self._blacklist_on_failure = False
        self._init = {}
        self._modules = {}
        self._reloads = {}
        self._status = {
            'all': {},
            'deprecated': {},
            'broken': {}
        }

    def start(self):
        with self._lock:
            if self.cfg.gt('plugins', 'enable'):
                self.log('start.', logger.INFO)
                self._to_blacklist = set()
                self._blacklist = set(utils.str_to_list(self.cfg.gt('plugins', 'blacklist')))
                self._whitelist = set(utils.str_to_list(self.cfg.gt('plugins', 'whitelist')))
                self._blacklist_on_failure = self.cfg.gt('plugins', 'blacklist_on_failure')

                self._init_all()
                self._start_all()
                self._update_blacklist()

                self._to_blacklist, self._blacklist, self._whitelist = None, None, None

    def stop(self):
        with self._lock:
            self._stop_all()
            if self.cfg.gt('plugins', 'enable') or self._modules:
                self.log('stop.', logger.INFO)
            self._status['broken'].clear(), self._status['deprecated'].clear(), self._status['all'].clear()
            self._modules, self._reloads = {}, {}

    def reload(self, diff: dict):
        with self._lock:
            self._reload_all(diff)

    def status(self, state: str) -> dict:
        return self._status.get(state, {})

    def _update_blacklist(self):
        self._to_blacklist -= self._blacklist
        if not self._to_blacklist:
            return
        to_blacklist = list(self._to_blacklist)
        to_blacklist.sort()
        to_blacklist = ','.join(to_blacklist)
        blacklist = self.cfg.gt('plugins', 'blacklist')
        blacklist = '{},{}'.format(blacklist, to_blacklist) if blacklist else to_blacklist
        self.log('Add to blacklist: {}'.format(to_blacklist), logger.INFO)
        self.cfg.update_from_dict({'plugins': {'blacklist': blacklist}})

    def _get_log(self, name: str):
        return self.log.add(name.capitalize())

    def _log(self, name, msg, lvl=logger.DEBUG):
        self.log.module(name.capitalize(), msg, lvl)

    def _init_all(self):
        for plugin in os.listdir(self.cfg.path['plugins']):
            plugin_dir = os.path.join(self.cfg.path['plugins'], plugin)
            plugin_path = os.path.join(plugin_dir, PLUG_FILE)
            module_name = 'plugins.{}'.format(plugin)
            if not os.path.isfile(plugin_path):
                continue
            self._target = None
            try:
                self._init_plugin(plugin_path, plugin_dir, module_name)
            except Exception as e:
                self.log('Error init {}: {}'.format(module_name, e), logger.ERROR)
                if self._target is not None:
                    if not (self._target in self._status['broken'] or self._target in self._status['deprecated']):
                        self._status['broken'][self._target] = plugin_dir
                    if self._blacklist_on_failure:
                        self._to_blacklist.add(self._target)
            if self._target is not None and self._target not in self._status['all']:
                self._status['all'][self._target] = plugin_dir
        if self._init:
            self.log('Init {}'.format(', '.join(key for key in self._init)))

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

        if not self._allow_by_name(name):
            return
        self._target = name

        reload = getattr(module, RELOAD, None)
        if reload is not None and not is_iterable(reload):
            raise RuntimeError('\'{}\' must be iterable or None'.format(RELOAD))

        api = getattr(module, API, None)
        if not isinstance(api, int):
            raise RuntimeError('\'{}\' missing or not int: {}, {}'.format(API, repr(api), type(api)))

        if api < self.cfg.API:
            if name not in self._status['deprecated']:
                self._status['deprecated'][name] = plugin_dir
            msg = 'Plugin \'{}\' deprecated. Plugin api: {}, terminal api: {}. Ignore.'.format(name, api, self.cfg.API)
            self.log(msg, logger.WARN)
            return

        self._init[name] = (getattr(module, ENTRYPOINT)(cfg=self.cfg, log=self._get_log(name), owner=self.own), reload)

    def _start_all(self):
        # special plugin
        plugin_updater = self._init.pop('plugin-updater', None)
        for name, (module, reload) in self._init.items():
            self._start_plugin(name, module, reload)
        if plugin_updater:
            self._start_plugin('plugin-updater', plugin_updater[0], plugin_updater[1])
        self._init = {}

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
            if self._blacklist_on_failure:
                self._to_blacklist.add(name)
            return
        self._modules[name] = module
        if reload and getattr(module, 'reload', None):
            self._reloads[name] = reload
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

    def _allow_by_name(self, name: str) -> bool:
        if self._whitelist and name not in self._whitelist:
            self.log('Ignore \'{}\': not whitelisted'.format(name), logger.DEBUG)
            return False
        if self._blacklist and name in self._blacklist:
            self.log('Ignore \'{}\': blacklisted'.format(name), logger.DEBUG)
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
