#!/usr/bin/env python3

from collections import OrderedDict

import logger

EQ = 1  # phrase equivalent
SW = 2  # phrase startswith - by default
EW = 3  # phrase endswith

NM = 'words_normal'  # normal mode
DM = 'words_debug'  # debug mode
ANY = 'words'  # Оба режима. by default for words


def get_mode_say(mode_):
    pretty = {NM: 'Обычный', DM: 'Отладка', ANY: 'Любой'}
    return pretty.get(mode_)


def get_enable_say(enable):
    pretty = {True: 'восстановлен', False: 'удален'}
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


class ModuleManager:
    def __init__(self, log, cfg, die_in, say):
        self._log = log
        self.cfg = cfg
        self.set_die_in = die_in
        self._say = say
        # Режим разработчика
        self.debug = False
        # Если установлено, будет всегда вызывать его
        self.one_way = None
        self.check_words = [NM, ANY]
        self.all = None
        # Для поиска по имени
        self.by_name = None
        self._code = 0

    def start(self):
        import modules
        self.all, conflict = modules.mod.get
        # Для поиска по имени
        self.by_name = {val['name']: key for key, val in self.all.items()}
        self._log('Загружены модули: {}'.format(', '.join([key for key in self.by_name])))
        if conflict:
            self._log(conflict, logger.WARN)

    def m_log(self, name, msg, *args):
        self._log('*{}*: {}'.format(name, msg), *args)

    def _set_one_way(self, f):
        self.one_way = f

    def _set_mod_enable(self, f, enable: bool):
        if f not in self.all:
            self._log('Module {} not found'.format(f), logger.WARN)
            return
        if self.all[f]['hardcoded']:
            self._log('Module {} hardcoded - not to change mode'.format(self.all[f].get('name', f)), logger.WARN)
            return
        if self.all[f]['enable'] == enable:
            self._log('Module {} already {}'.format(self.all[f].get('name', f), get_enable_say(enable)), logger.INFO)
        self.all[f]['enable'] = enable

    def _set_mod_mode(self, f, mode_):
        if f not in self.all:
            self._log('Module {} not found'.format(f), logger.WARN)
            return
        if self.all[f]['hardcoded']:
            self._log('Module {} hardcoded - not to change mode'.format(self.all[f].get('name', f)), logger.WARN)
            return
        if self.all[f]['mode'] == mode_:
            self._log('Module {} already {}'.format(self.all[f].get('name', f), get_mode_say(mode_)), logger.INFO)
        self.all[f]['mode'] = mode_

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
        self.check_words = [NM, ANY] if not mode_ else [DM, ANY]
        self.debug = mode_
        return True

    def tester(self, phrase: str, call_me=None):
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
            self._log('Вы ничего не сказали?', logger.DEBUG)
            return self._return_wrapper(None, None)

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

        return self._return_wrapper(None, [Say('Соответствие фразе не найдено: {}'.format(phrase))])

    def words_by_f(self, f):
        def allow_any():
            if not val['enable']:
                return False
            if val['mode'] == ANY:
                return True
            return self.debug == (val['mode'] == DM)

        val = self.all[f]
        for words_target in self.check_words:
            if words_target in val and allow_any():
                for check in val[words_target]:
                    if isinstance(check, str):
                        yield check, SW
                    else:
                        yield check[0], check[1]

    def _words_iter(self):  # Функция, фраза, режим проверки
        for key in self.all:
            for words in self.words_by_f(key):
                yield key, words[0], words[1]

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
                f_by_key = {
                    'debug': self._set_debug,
                    'one_way': self._set_one_way,
                    'mod_mode': self._set_mod_mode,
                    'mod_enable': self._set_mod_enable,
                    'die': self.set_die_in,
                }
                for key, val in reply.set.items():
                    if key in f_by_key:
                        if isinstance(val, dict):
                            f_by_key[key](**val)
                        elif not isinstance(val, (tuple, list)):
                            f_by_key[key](val)
                        else:
                            f_by_key[key](*val)
            elif reply_type is Say:
                result = reply.text
            elif reply_type is Ask:
                result = reply.text
                asking = f
            elif reply_type is SayLow:
                for text in reply.iter():
                    self._say(*text)

        return result, asking

    def _call_func(self, f, *args):
        self._log('Захвачено {}'.format(f), logger.DEBUG)
        return f(self, *args)

    def _call_this(self, obj, *args):
        if callable(obj):
            return self._call_func(obj, *args)
        elif isinstance(obj, str) and obj in self.by_name:
            return self._call_func(self.by_name[obj], *args)
        return Next


class ModuleWrapper:
    def __init__(self):
        # Приоритет проверки будет по порядку появления в коде
        self.__is_all = OrderedDict()
        self.__conflict = {}  # hotword: [name, name, ..] Просто для информации
        self.__words = {}  # Лучше что-бы фразы не повторялись
        self.__names = set()  # Имя модуля уникально

        self.__prepare_all_ = None
        self.__prepare_conflict_ = None

    def _prepare_is_all(self):
        if self.__prepare_all_ is not None:
            return self.__prepare_all_
        self.__prepare_all_ = OrderedDict()
        must_be = ['name', 'desc', 'mode']
        for key, val in self.__is_all.items():
            for item in must_be:
                if item not in val:
                    raise RuntimeError('Key {} not in {}'.format(item, val.get('name', key)))
            if not [x for x in [NM, DM, ANY] if x in val]:
                raise RuntimeError('Module {} not have words'.format(val.get('name', key)))
            val['hardcoded'] = val.get('hardcoded', False)
            self.__prepare_all_[key] = val
        del self.__is_all
        return self.__prepare_all_

    def _name(self, f):
        if self.__prepare_all_:
            return str(self.__prepare_all_.get(f, {}).get('name', f))
        else:
            return str(self.__is_all.get(f, {}).get('name', f))

    def _prepare_conflict(self):
        if self.__prepare_conflict_ is not None:
            return self.__prepare_conflict_
        self.__prepare_conflict_ = ''
        if len(self.__conflict):
            self.__prepare_conflict_ = 'Возможны {} конфликтов: '.format(len(self.__conflict))
            for key, val in self.__conflict.items():
                self.__prepare_conflict_ += '\'{}\' -> [{}] '.format(key, ', '.join(self._name(k) for k in val))
        del self.__conflict
        return self.__prepare_conflict_

    @property
    def get(self):
        if self.__words:
            del self.__words
            self.__words = None
        if self.__names:
            del self.__names
            self.__names = None
        return self._prepare_is_all(), self._prepare_conflict()

    def _add(self, f, **kwargs):
        if f not in self.__is_all:
            self.__is_all[f] = {'enable': True}
        self.__is_all[f].update(kwargs)

    def _add_phrases(self, f, param, phrases: list):
        name = self.__is_all.get(f, {}).get('name', f)
        for target in phrases:
            if isinstance(target, list) and len(target) == 2 and target[1] in [EQ, SW, EW]:
                check = target[0]
            elif isinstance(target, str):
                check = target
            else:
                raise RuntimeError('Bad word \'{}\' from \'{}\''.format(target, name))

            if check in self.__words:
                prevent = self.__words[check]
                if prevent == f:
                    pass
                elif check in self.__conflict:
                    self.__conflict[check].add(f)
                else:
                    self.__conflict[check] = {prevent, f}
                self.__words[check] = f
            else:
                self.__words[check] = f
        self._add(f, **{param: phrases})

    def name(self, mode_, name, description):
        # Дефолтный режим, имя и описание
        # Изначально все модули включены. Отключенные модули ничего не триггерят
        name = name.lower()
        if not name or name in self.__names:
            raise RuntimeError('Module name must be set and unique: {}'.format(name))
        if mode_ not in [NM, DM, ANY]:
            raise RuntimeError('Unknown module {} mode: {}'.format(name, mode_))
        self.__names.add(name)

        def wrap(f):
            self._add(f, mode=mode_, name=name, desc=description)
            return f
        return wrap

    def phrase(self, phrases_, mode_=None):
        # Если mode_ задан, фразы доступны только в заданном режиме
        # Если нет или ANY, доступны в любом режиме
        # При условии что сам  модулю в этом режиме, или в ANY
        # Порядок обхода в обычном - normal, any. В дебаг - debug, any
        # Фразаы могут быть списком элементов. Элемент может быть фразой или фразой и режимом сравнения.
        # Пустая фраза будет триггерить все
        mode_ = mode_ or ANY
        if mode_ not in [NM, DM, ANY]:
            raise RuntimeError('Unknown phrases mode: {}'.format(mode_))
        if isinstance(phrases_, str) or \
                (isinstance(phrases_, list) and len(phrases_) == 2 and phrases_[1] in [EQ, SW, EW]):
            phrases_ = [phrases_]

        for idx in range(len(phrases_)):
            if isinstance(phrases_[idx], str):
                phrases_[idx] = phrases_[idx].lower()
            elif isinstance(phrases_[idx], list) and isinstance(phrases_[idx][0], str):
                phrases_[idx][0] = phrases_[idx][0].lower()
            else:
                raise RuntimeError('Hot words {} - invalid format'.format(phrases_[idx]))

        def wrap(f):
            self._add_phrases(f, mode_, phrases_)
            return f
        return wrap

    def hardcoded(self):
        # Модуль нельзя переключать между режимами. Например менеджер, режим отладки
        def wrap(f):
            self._add(f, hardcoded=True)
            return f
        return wrap
