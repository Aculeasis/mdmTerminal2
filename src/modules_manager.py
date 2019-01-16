#!/usr/bin/env python3

import importlib
import sys
import threading
from collections import OrderedDict

import logger
from languages import MODULES_MANAGER as LNG
from owner import Owner

EQ = 1  # phrase equivalent
SW = 2  # phrase startswith - by default
EW = 3  # phrase endswith
ALL_COMPARE_MODES = (EQ, SW, EW)

NM = 'words_normal'  # normal mode
DM = 'words_debug'  # debug mode
ANY = 'words'  # Оба режима. by default for words
ALL_MODES = (NM, DM, ANY)


def get_mode_say(mode_):
    pretty = {NM: LNG['say_nm'], DM: LNG['say_dm'], ANY: LNG['say_any']}
    return pretty.get(mode_)


def get_enable_say(enable):
    pretty = {True: LNG['say_enable'], False: LNG['say_disable']}
    return pretty.get(enable)


class Next:  # Ошиблись модулем. Ищем дальше
    pass


class Set:  # Меняем установки
    def __init__(self, **kwargs):
        self.set = kwargs


class Say:  # Говорим что-то
    def __init__(self, text):
        self.text = text


class Ask(Say):  # Переспрашиваем. Ответ придет туда, откуда пришел Ask
    pass


class SayLow:  # Говорим с низким приоритетом
    def __init__(self, phrases, wait=0):
        if isinstance(phrases, str):
            self.texts = [[phrases, wait]]
        else:
            self.texts = phrases

    def iter(self):
        for text in self.texts:
            if isinstance(text, str):
                yield text, 0
            else:
                yield text


class DynamicModule:
    def __init__(self, callback, mode_, phrases=None):
        self._is_ok = mode_ in ALL_MODES and callback
        self._cb = callback
        self._mode = mode_
        self._phrases = {}
        if phrases is not None:
            self.phrase(phrases, mode_)

    @property
    def ok(self) -> bool:
        return self._is_ok and self._phrases

    @property
    def callback(self):
        return self._cb

    @property
    def get(self) -> dict:
        if not self.ok:
            raise RuntimeError('Module is broken')
        data = {'enable': True, 'mode': self._mode}
        data.update(self._phrases)
        return data

    def phrase(self, phrases, mode_=None) -> bool:
        mode_ = mode_ or ANY
        if not (self._is_ok and mode_ in ALL_MODES):
            return False
        try:
            phrases = parse_phrases('', phrases)
        except RuntimeError:
            return False
        if mode_ not in self._phrases:
            self._phrases[mode_] = []
        self._phrases[mode_].extend(phrases)
        return True


class ModuleManager:
    def __init__(self, log, cfg, owner: Owner):
        (self._log, self._m_log) = log
        self.cfg = cfg
        self.own = owner
        # Режим разработчика
        self.debug = False
        # Если установлено, будет всегда вызывать его
        self.one_way = None
        self._check_words = [NM, ANY]
        self.all = None
        # Для поиска по магическому имени (.__name__)
        self._by_f_name = None
        # Для поиска по имени (['name'])
        self.by_name = None
        # код вызова
        self._code = 0
        # Название модели которым был активирован терминал или None
        self.model = None
        # Имя модуля (.__name__) который вызван в данный момент.
        self._module_name = None
        # Без расширения
        self._cfg_name = 'modules'
        self._cfg_options = ['enable', 'mode', 'hardcoded']
        # Не проверяем данные модули на конфликты
        self._no_check = ['majordomo', 'terminator']
        self._lock = threading.Lock()
        # Динамические модули
        self._ext_all = OrderedDict()
        self._ext_lock = threading.Lock()

    def insert_module(self, module: DynamicModule) -> bool:
        if not isinstance(module, DynamicModule):
            return False
        with self._ext_lock:
            if not module.ok or module.callback in self._ext_all:
                return False
            self._ext_all[module.callback] = module.get
            self._ext_all.move_to_end(module.callback, last=False)
            return True

    def extract_module(self, callback) -> bool:
        with self._ext_lock:
            if callback in self._ext_all:
                del self._ext_all[callback]
                return True
            return False

    def start(self):
        self.reload()

    def reload(self):
        with self._lock:
            self._module_name, self.one_way = None, None
            self._code = 0
            self.debug = False

            modules = importlib.import_module(self._cfg_name)
            self.all = modules.mod.get
            del sys.modules[self._cfg_name]
            del modules

            self._by_f_name = {key.__name__: key for key in self.all}
            self.by_name = {val['name']: key for key, val in self.all.items()}
            # Загружаем настройки модулей
            self._set_options(self.cfg.load_dict(self._cfg_name))
            self._print_info()
            self._conflicts_checker()

    def stop(self):
        # Сохраняем настройки модулей
        if self.all:
            self.cfg.save_dict(self._cfg_name, self._get_options())

    def _print_info(self):
        active, inactive, disable = [], [], []
        for module in self.all.values():
            if not module['enable']:
                disable.append(module['name'])
            elif module['mode'] in (NM, ANY):
                active.append(module['name'])
            else:
                inactive.append(module['name'])
        if disable:
            self._log(LNG['disable_m'].format(', '.join(disable)))
        if inactive:
            self._log(LNG['inactive_m'].format(', '.join(inactive)))
        if active:
            self._log(LNG['active_m'].format(', '.join(active)), logger.INFO)

    def _conflicts_checker(self):
        # Ищет возможные конфликты в модулях. Разные режимы сравниваются отдельно
        result = {}
        self._set_debug(True)
        result[DM] = self._conflicts_finder()
        self._set_debug(False)
        result[NM] = self._conflicts_finder()
        for key, val in result.items():
            msg = []
            for target, data in val.items():
                msg.append('{}: [{}]'.format(target, ', '.join([self.all[x]['name'] for x in data])))
            if msg:
                self._log(LNG['conflict_found'].format(get_mode_say(key), ', '.join(msg)), logger.WARN)

    def _conflicts_finder(self) -> dict:
        conflicts = {}
        all_ = [x for x in self._words_iter()]  # Метод, слово, режим слова
        count = len(all_)
        for num in range(count):
            sample = all_[num]
            for target in all_[num:]:
                if sample[0] == target[0] or sample[0].__name__ in self._no_check:
                    continue
                if self._words_compare(sample[1:], target[1:]):  # Конфликт
                    if sample[1] not in conflicts:
                        conflicts[sample[1]] = set()
                    conflicts[sample[1]].add(sample[0])
                    conflicts[sample[1]].add(target[0])
        return conflicts

    @staticmethod
    def _words_compare(one, two) -> bool:  # [фраза, метод]
        if len(one[0]) > len(two[0]):
            return False
        if one[0] == '':  # Перехватит все
            return True
        if one[0] == two[0]:
            return True
        if two[0].startswith(one[0]) and one[1] in [EQ, SW] and two[1] != EW:
            return True
        if one[1] == EW and two[1] in [EQ, EW] and two[0].endswith(one[0]):
            return True
        return False

    def _get_options(self):
        data = {}
        for func, val in self.all.items():
            data[func.__name__] = {key: val[key] for key in self._cfg_options}
        return data

    def __option_check(self, name, option: str, val) -> bool:
        if option in ['enable', 'hardcoded']:
            if isinstance(val, bool):
                return True
            else:
                self._log('{} bad option type. {} must be bool, not {}'.format(name, option, type(val)), logger.ERROR)
        elif option == 'mode':
            if val in ALL_MODES:
                return True
            else:
                self._log('{} unknown mode value - {}'.format(name, val), logger.ERROR)
        else:
            self._log('{} get unknown option \'{}\''.format(name, option), logger.ERROR)
        return False

    def _set_options(self, data: dict or None):
        if data is None:
            return
        # магическое имя функции: ссылка
        for key, val in data.items():
            f_name = self._by_f_name.get(key)
            if not f_name:
                continue
            for option in self._cfg_options:
                if option in val and self.__option_check(key, option, val[option]):
                    self.all[f_name][option] = val[option]

    def log(self, *args):
        self._m_log(self._module_name, *args)

    def _set_one_way(self, f):
        self.one_way = f

    def _set_mod_enable(self, f, enable: bool):
        if not self.__set_mod_check(f):
            return
        if self.all[f]['enable'] == enable:
            self._log('Module {} already {}'.format(self.all[f].get('name', f), get_enable_say(enable)), logger.INFO)
        self.all[f]['enable'] = enable

    def _set_mod_mode(self, f, mode_):
        if not self.__set_mod_check(f):
            return
        if self.all[f]['mode'] == mode_:
            self._log('Module {} already {}'.format(self.all[f].get('name', f), get_mode_say(mode_)), logger.INFO)
        self.all[f]['mode'] = mode_

    def __set_mod_check(self, f):
        if f not in self.all:
            self._log('Module {} not found'.format(f), logger.WARN)
            return False
        if self.all[f]['hardcoded']:
            self._log('Module {} hardcoded - not to change mode'.format(self.all[f].get('name', f)), logger.WARN)
            return False
        return True

    @property
    def get_one_way(self):
        return self.one_way

    @property
    def is_debug(self):
        return self.debug

    @property
    def code(self):  # Активировано 0 - фразой, 1 - через ask, 2 - через one_way
        return self._code

    def _set_debug(self, mode_: bool):
        if self.is_debug == mode_:
            return False
        self._check_words = [NM, ANY] if not mode_ else [DM, ANY]
        self.debug = mode_
        return True

    def _phrases_testing(self, phrase, phrase_check):
        reply = Next
        self._code = 0
        for f, words, mode_ in self._words_iter():
            if words == '':
                reply = self._call_func(f, phrase_check, phrase)
            elif mode_ == EQ:
                if phrase_check == words:
                    reply = self._call_func(f, words, phrase)
            elif mode_ == SW:
                if phrase_check.startswith(words):
                    reply = self._call_func(f, words, phrase[len(words):].strip())
            elif mode_ == EW:
                if phrase_check.endswith(words):
                    reply = self._call_func(f, words, phrase[:-len(words)].strip())

            if reply is not Next:
                return self._return_wrapper(f, reply)
        return self._return_wrapper(None, None)

    def tester(self, phrase: str, call_me=None, model=None):
        with self._lock:
            self.model = model
            reply = Next
            f = None
            phrase_check = phrase.lower()

            if self.one_way:
                self._code = 2
                reply = self._call_this(self.one_way, phrase_check, phrase)
                f = self.one_way
            if reply is Next and call_me:
                self._code = 1
                reply = self._call_this(call_me, phrase_check, phrase)
                f = call_me

            if reply is not Next:
                return self._return_wrapper(f, reply)

            if not phrase:
                self._log(LNG['not_say'], logger.DEBUG)
                return self._return_wrapper(None, None)

            return self._phrases_testing(phrase, phrase_check)

    def words_by_f(self, f, modules=None):
        def allow_any():
            if not val['enable']:
                return False
            if val['mode'] == ANY:
                return True
            return self.debug == (val['mode'] == DM)

        val = (modules or self.all)[f]
        for words_target in self._check_words:
            if words_target in val and allow_any():
                for check in val[words_target]:
                    if isinstance(check, str):
                        yield check, SW
                    else:
                        yield check[0], check[1]

    def _words_iter(self):  # Функция, фраза, режим проверки
        if self._ext_all:
            with self._ext_lock:
                yield from self._words_iter_target(self._ext_all)
        yield from self._words_iter_target(self.all)

    def _words_iter_target(self, target):
        for key in target:
            for words in self.words_by_f(key, target):
                yield key, words[0], words[1]

    def _processing_set(self, to_set: Set or None):
        if to_set is None:
            return
        f_by_key = {
            'debug': self._set_debug,
            'one_way': self._set_one_way,
            'mod_mode': self._set_mod_mode,
            'mod_enable': self._set_mod_enable,
            'die': self.own.die_in,
        }
        for key, val in to_set.set.items():
            if key in f_by_key:
                if isinstance(val, dict):
                    f_by_key[key](**val)
                elif not isinstance(val, (tuple, list)):
                    f_by_key[key](val)
                else:
                    f_by_key[key](*val)

    def _return_wrapper(self, f, replies):
        if replies is None:
            return None, None
        if not isinstance(replies, (tuple, list)):
            replies = [replies]
        result = None
        asking = None
        for reply in replies:
            reply_type = type(reply)
            if reply_type is Set:
                self._processing_set(reply)
            elif reply_type is Say:
                result = reply.text
            elif reply_type is Ask:
                result = reply.text
                asking = f  # можно заменить на f.__name__ если передача ссылки на объект станет невозможной
            elif reply_type is SayLow:
                for text in reply.iter():
                    self.own.say(*text)
        return result, asking

    def _call_func(self, f, *args):
        try:
            self._module_name = f.__name__
        except AttributeError:
            self._module_name = str(f)
        self._log(LNG['catch'].format(f), logger.DEBUG)
        return f(self, *args)

    def _call_this(self, obj, *args):
        if callable(obj):
            # noinspection PyTypeChecker
            return self._call_func(obj, *args)
        elif isinstance(obj, str) and obj in self._by_f_name:
            return self._call_func(self._by_f_name[obj], *args)
        self._log('Unknown object called: {}, type: {}'.format(obj, type(obj)), logger.ERROR)
        return Next


class ModuleWrapper:
    def __init__(self):
        # Приоритет проверки будет по порядку появления в коде
        self.__is_all = OrderedDict()
        self.__names = set()  # Имя модуля уникально

        self.__prepare_all_ = None

    def _prepare_is_all(self):
        if self.__prepare_all_ is not None:
            return self.__prepare_all_
        self.__prepare_all_ = OrderedDict()
        must_be = ['name', 'desc', 'mode']
        unique_magic_names = {}
        for key, val in self.__is_all.items():
            for item in must_be:
                if item not in val:
                    raise RuntimeError('Key {} not in {}'.format(item, val.get('name', key)))
            if not [x for x in ALL_MODES if x in val]:
                raise RuntimeError('Module {} not have words'.format(val.get('name', key)))
            val['hardcoded'] = val.get('hardcoded', False)
            f_name = key.__name__
            if f_name in unique_magic_names:
                msg = 'Magic function name must be unique, \'{}\' conflicts with \'{}\'. Name - {}'
                old_name = self.__is_all[unique_magic_names[f_name]]['name']
                new_name = self.__is_all[key]['name']
                raise RuntimeError(msg.format(old_name, new_name, f_name))
            unique_magic_names[f_name] = key
            self.__prepare_all_[key] = val
        del self.__is_all
        return self.__prepare_all_

    @property
    def get(self):
        if self.__names:
            del self.__names
            self.__names = None
        return self._prepare_is_all()

    def _add(self, f, **kwargs):
        if f not in self.__is_all:
            self.__is_all[f] = {'enable': True}
        self.__is_all[f].update(kwargs)

    def _add_phrases(self, f, param, phrases: list or str or tuple):
        name = self.__is_all.get(f, {}).get('name', f)
        phrases = parse_phrases(name, phrases)

        self._add(f, **{param: phrases})

    def name(self, mode_, name, description):
        # Дефолтный режим, имя и описание
        # Изначально все модули включены. Отключенные модули ничего не триггерят
        name = name.lower()
        if not name or name in self.__names:
            raise RuntimeError('Module name must be set and unique: {}'.format(name))
        if mode_ not in ALL_MODES:
            raise RuntimeError('Unknown module {} mode: {}'.format(name, mode_))
        self.__names.add(name)

        def wrap(f):
            self._add(f, mode=mode_, name=name, desc=description)
            return f
        return wrap

    def phrase(self, phrases, mode_=None):
        # Если mode_ задан, фразы доступны только в заданном режиме
        # Если нет или ANY, доступны в любом режиме
        # При условии что сам  модулю в этом режиме, или в ANY
        # Порядок обхода в обычном - normal, any. В дебаг - debug, any
        # Фразаы могут быть списком элементов. Элемент может быть фразой или фразой и режимом сравнения.
        # Пустая фраза будет триггерить все
        mode_ = mode_ or ANY
        if mode_ not in ALL_MODES:
            raise RuntimeError('Unknown phrases mode: {}'.format(mode_))

        def wrap(f):
            self._add_phrases(f, mode_, phrases)
            return f
        return wrap

    def hardcoded(self):
        # Модуль нельзя переключать между режимами. Например менеджер, режим отладки
        def wrap(f):
            self._add(f, hardcoded=True)
            return f
        return wrap


def list_to_tuple(data: list) -> tuple:
    return tuple(key if not isinstance(key, list) else list_to_tuple(key) for key in data)


def parse_phrases(name, phrases):
    if isinstance(phrases, str) or \
            (isinstance(phrases, (tuple, list)) and len(phrases) == 2 and phrases[1] in ALL_COMPARE_MODES):
        phrases = [phrases]
    for idx in range(len(phrases)):
        if isinstance(phrases[idx], str):
            phrases[idx] = phrases[idx].lower()
        elif isinstance(phrases[idx], (tuple, list)) and isinstance(phrases[idx][0], str) \
                and len(phrases[idx]) == 2 and phrases[idx][1] in ALL_COMPARE_MODES:
            phrases[idx][0] = phrases[idx][0].lower()
        else:
            raise RuntimeError('Bad word \'{}\' from \'{}\''.format(phrases[idx], name))
    return list_to_tuple(phrases)
