import importlib
import os
import sys
import time
import threading
from copy import deepcopy
from .deep_check import DeepChecker, ERROR

DEFAULT_LANG = 'ru'

# Словарь локализации, ключи - str, значения - str, None или callable.
_LNG = {}

# Словари для локализации, заполняются динамически
# Могут содержать все что угодно - строки, классы, списки и т.д.
LANG_CODE = {}
YANDEX_EMOTION = {}
# Спикеры валидные для данного языка и их произношение
YANDEX_SPEAKER = {}
RHVOICE_SPEAKER = {}
AWS_SPEAKER = {}


class _LangSetter:
    # Список заполняемых словарей
    DICTS = (
        '_LNG',
        'LANG_CODE', 'YANDEX_EMOTION', 'YANDEX_SPEAKER', 'RHVOICE_SPEAKER', 'AWS_SPEAKER'
    )
    UNIQUE = ('_LNG', 'RHVOICE_SPEAKER', 'AWS_SPEAKER')
    PATH = os.path.dirname(os.path.abspath(__file__))

    def __init__(self):
        self.lang = None
        self.deep = False
        self._lock = threading.Lock()
        self._load_time = 0
        self.log = lambda x, y: print(x, y)
        self._load_error(DEFAULT_LANG, self.__call__(DEFAULT_LANG))

    @property
    def load_time(self):
        try:
            return self._load_time
        finally:
            self._load_time = 0

    def set_logger(self, logger):
        self.log = logger

    def __call__(self, lang_name: str, deep=False):
        self.deep = deep
        # Если deep задан выполняем глубокую проверку
        if lang_name == self.lang:
            return
        if not lang_name or not isinstance(lang_name, str):
            return 'Bad name - \'{}\''.format(lang_name)

        path = os.path.join(self.PATH, lang_name + '.py')
        if not os.path.isfile(path):
            return 'File not found: {}'.format(path)
        with self._lock:
            self._load_time = time.time()
            if self.lang is not None and self.lang != DEFAULT_LANG:
                # Восстанавливаем все словари из языка по умолчанию
                self._load_error(DEFAULT_LANG, self._load('languages.' + DEFAULT_LANG))
            self.lang = lang_name
            module = 'languages.' + lang_name
            try:
                return self._load(module, deep=None if not deep else DeepChecker(self.log, module))
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


def _f_err(msg, txt, val, args, kwargs, e: Exception = ''):
    set_lang.log('{}, txt={}, val={}, args={}, kwargs={}: {}'.format(msg, repr(txt), repr(val), args, kwargs, e), ERROR)


def F(txt: str, *args, **kwargs) -> str:
    if txt in _LNG:
        if _LNG[txt] is not None:
            val = _LNG[txt]
        else:
            if set_lang.lang != DEFAULT_LANG and set_lang.deep:
                _f_err('None key in custom language', txt, None, args, kwargs)
            val = txt
    else:
        if set_lang.lang == DEFAULT_LANG:
            _f_err('Key missing in default language', txt, '', args, kwargs)
        val = txt
    if isinstance(val, str):
        if args or kwargs:
            try:
                return val.format(*args, **kwargs)
            except (KeyError, IndexError) as e:
                _f_err('format error', txt, val, args, kwargs, e)
                try:
                    return txt.format(*args, **kwargs)
                except (KeyError, IndexError):
                    pass
        return txt
    elif callable(val):
        try:
            return val(txt, *args, **kwargs)
        except Exception as e:
            _f_err('Call error', txt, val, args, kwargs, e)
        return txt
    else:
        _f_err('Wrong type', txt, val, args, kwargs)
    return '=== localization error ==='
