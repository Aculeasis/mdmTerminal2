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

# Словари локализации, заполняются динамически
# Могут содержать все что угодно - строки, классы, списки и т.д.
LANG_CODE = {}
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
# Спикеры валидные для данного языка и их произношение
YANDEX_SPEAKER = {}
RHVOICE_SPEAKER = {}
AWS_SPEAKER = {}
# Спикеры по умолчанию.
DEFAULT_SPEAKERS = {}


class _LangSetter:
    # Список заполняемых словарей
    DICTS = (
        'LANG_CODE', 'CONFIG', 'LOADER', 'LOGGER', 'MODULES', 'MODULES_MANAGER', 'MPD_CONTROL', 'PLAYER', 'SERVER',
        'STTS', 'TERMINAL', 'UPDATER',
        'YANDEX_EMOTION', 'YANDEX_SPEAKER', 'RHVOICE_SPEAKER', 'AWS_SPEAKER', 'DEFAULT_SPEAKERS'
    )
    UNIQUE = ('RHVOICE_SPEAKER', 'AWS_SPEAKER')
    PATH = os.path.dirname(os.path.abspath(__file__))

    def __init__(self):
        self._lang = None
        self._lock = threading.Lock()
        self._load_time = 0

        self._load_error(DEFAULT_LANG, self.__call__(DEFAULT_LANG))

    @property
    def language_name(self):
        return self._lang

    @property
    def load_time(self):
        try:
            return self._load_time
        finally:
            self._load_time = 0

    def __call__(self, lang_name: str, print_=None):

        # Если print_ задан выполняем глубокую проверку

        if lang_name == self._lang:
            return
        if not lang_name or not isinstance(lang_name, str):
            return 'Bad name - \'{}\''.format(lang_name)

        path = os.path.join(self.PATH, lang_name + '.py')
        if not os.path.isfile(path):
            return 'File not found: {}'.format(path)
        with self._lock:
            self._load_time = time.time()
            if self._lang is not None and self._lang != DEFAULT_LANG:
                # Восстанавливаем все словари из языка по умолчанию
                self._load_error(DEFAULT_LANG, self._load('languages.' + DEFAULT_LANG))
            self._lang = lang_name
            module = 'languages.' + lang_name
            try:
                return self._load(module, deep=None if not print_ else DeepChecker(print_, module))
            finally:
                self._load_time = time.time() - self._load_time

    def _load(self, module, deep: None or DeepChecker = None):
        lib = importlib.import_module(module)
        miss_keys = []
        wrong_keys = []
        msg = ''
        if deep is not None:
            deep.start()
        for key in self.DICTS:
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
            if key in self.UNIQUE:
                globals()[key].clear()
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

    @staticmethod
    def _load_error(lang_name, err):
        if err:
            raise RuntimeError('Error load default language \'{}\': {}'.format(lang_name, err))


set_lang = _LangSetter()
