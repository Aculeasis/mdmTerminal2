import importlib
import os
import sys
import time
import threading
from copy import deepcopy
from .deep_check import DeepChecker

# Используется для первичной инициализации, должен содержать все словари локализации
# Значение отсутствющие в других языках будут взяты из него.
DEFAULT_LANG = 'ru'

# Словари локализаций
# Могут содержать все что угодно - строки, классы, списки и т.д.
CONFIG = {}
LOADER = {}
LOGGER = {}
MODULES = {}
MODULES_MANAGER = {}
MPD_CONTROL = {}
PLAYER = {}
SERVER = {}
STTS = {}
TERMINAL = {}
UPDATER = {}

YANDEX_EMOTION = {}
YANDEX_SPEAKER = {}
RHVOICE_SPEAKER = {}

# Список копируемых словарей
_dicts = ('CONFIG', 'LOADER', 'LOGGER', 'MODULES', 'MODULES_MANAGER', 'MPD_CONTROL', 'PLAYER', 'SERVER', 'STTS',
          'TERMINAL', 'UPDATER', 'YANDEX_EMOTION', 'YANDEX_SPEAKER', 'RHVOICE_SPEAKER')

_path = os.path.dirname(os.path.abspath(__file__))
_lang = None
_lock = threading.Lock()


def load_time():
    return _load_time


def set_lang(lang_name, print_=None):
    # Если print_ задан выполняем глубокую проверку
    global _lock, _lang, _load_time
    if lang_name == _lang:
        return
    if not lang_name or not isinstance(lang_name, str):
        return 'Bad name - \'{}\''.format(lang_name)

    path = os.path.join(_path, lang_name + '.py')
    if not os.path.isfile(path):
        return 'File not found: {}'.format(path)
    with _lock:
        _load_time = time.time()
        if _lang is not None and _lang != DEFAULT_LANG:
            # Восстанавливаем все словари из языка по умолчанию
            _load_error(DEFAULT_LANG, _load('languages.' + DEFAULT_LANG, True))
        _lang = lang_name
        module = 'languages.' + lang_name
        try:
            return _load(module, deep=None if not print_ else DeepChecker(print_, module))
        finally:
            _load_time = time.time() - _load_time


def _load(module, replace=False, deep: None or DeepChecker=None):
    lib = importlib.import_module(module)
    miss_keys = []
    wrong_keys = []
    msg = ''
    if deep is not None:
        deep.start()
    for key in _dicts:
        if key not in globals():
            raise RuntimeError('{} missing in. FIXME!'.format(key))
        if not isinstance(globals()[key], dict):
            raise RuntimeError('{} not a dict. FIXME!'.format(key))
        if key not in lib.__dict__:
            miss_keys.append(key)
            continue
        if not isinstance(lib.__dict__[key], dict):
            wrong_keys.append(key)
            continue
        if deep is not None:
            deep.check(key, globals()[key], lib.__dict__[key])
        if replace:
            globals()[key] = deepcopy(lib.__dict__[key])
        else:
            globals()[key].update(deepcopy(lib.__dict__[key]))
    if deep is not None:
        deep.end()
    del sys.modules[module]
    del lib
    if miss_keys:
        msg = 'missing dict: {}. '.format(', '.join(miss_keys))
    if wrong_keys:
        msg += 'Not a dict: {}.'.format(', '.join(wrong_keys))
    return msg or None


def _load_error(lang_name, err):
    if err:
        raise RuntimeError('Error load default language \'{}\': {}'.format(lang_name, err))


_load_error(DEFAULT_LANG, set_lang(DEFAULT_LANG))
