#!/usr/bin/env python3

import wikipedia

import logger
import utils
from languages import YANDEX_SPEAKER, YANDEX_EMOTION, RHVOICE_SPEAKER, AWS_SPEAKER, LANG_CODE, F
from modules_manager import EQ
from modules_manager import ModuleWrapper, get_mode_say, get_enable_say
from modules_manager import NM, DM, ANY
from modules_manager import Next, Set, Say, Ask, SayLow

wikipedia.set_lang(LANG_CODE['ISO'])
mod = ModuleWrapper()


@mod.name(ANY, F('Блокировка'), F('Включение/выключение блокировки терминала'))
@mod.phrase([F('блокировка'), EQ])
def lock(self, phrase, *_):
    if self.get_one_way is lock:
        if phrase == F('блокировка'):
            return Set(one_way=None), Say(F('Блокировка снята'))
        else:
            return Say(F('блокировка'))
    else:
        return Set(one_way=lock), Say(F('Блокировка включена'))


@mod.name(ANY, F('Отладка'), F('Режим настройки и отладки'))
@mod.phrase([F('режим разработчика'), EQ], NM)
@mod.phrase([F('выход'), EQ], DM)
@mod.hardcoded()
def debug(_, phrase, *__):
    if phrase == F('выход'):
        return Set(debug=False), Say(F('Внимание! Выход из режима разработчика'))
    elif phrase == F('режим разработчика'):
        msg = 'Внимание! Включён режим разработчика. Для возврата в обычный режим скажите \'выход\''
        return Set(debug=True), Say(F(msg))
    return Next


@mod.name(DM, F('Менеджер'), F('Управление модулями'))
@mod.phrase([F('активировать везде'), F('активировать'), F('деактивировать'), F('удалить'), F('восстановить')], DM)
@mod.hardcoded()
def manager(self, phrase, mod_name):
    mod_name = mod_name.lower()
    if mod_name not in self.by_name:
        self.log(F('Модуль {} не найден', mod_name), logger.INFO)
        return Next
    mod_ = self.by_name[mod_name]
    if self.all[mod_]['hardcoded']:
        return Say(F('Модуль {} системный, его нельзя настраивать', mod_name))

    modes = {F('активировать'): NM, F('деактивировать'): DM, F('активировать везде'): ANY}
    enables = {F('удалить'): False, F('восстановить'): True}
    if phrase in modes:
        if not self.all[mod_]['enable']:
            return Say(F('Модуль {} удален. Вначале его нужно восстановить', mod_name))
        new_mode = modes[phrase]
        if self.all[mod_]['mode'] == new_mode:
            return Say(F('Модуль {} уже в режиме {}', mod_name, get_mode_say(new_mode)))
        say = F('Теперь модуль {} доступен в режиме {}', mod_name, get_mode_say(new_mode))
        return Say(say), Set(mod_mode=[mod_, new_mode])
    elif phrase in enables:
        enable = enables[phrase]
        if self.all[mod_]['enable'] == enable:
            return Say(F('Модуль {} и так {}', mod_name, get_enable_say(enable)))
        say = F('Модуль {} {}', mod_name, get_enable_say(enable))
        return Say(say), Set(mod_enable=[mod_, enable])
    else:
        self.log(F('Это невозможно, откуда тут {}', phrase), logger.CRIT)
        return Next


@mod.name(DM, F('Скажи'), F('Произнесение фразы'))
@mod.phrase(F('Скажи'))
def this_say(_, __, phrase):
    return Say(phrase) if phrase else None


@mod.name(ANY, F('Ничего'), F('Ничего'))
@mod.phrase([F('Ничего'), EQ])
def this_nothing(*_):
    pass


@mod.name(DM,
          F('считалка'), F('Считалка до числа. Или от числа до числа. Считалка произносит не больше 20 чисел за раз'))
@mod.phrase([F('сосчитай'), F('считай'), F('посчитай')])
def counter(_, __, cmd):
    max_count = 20
    minus = F('минус') + ' '
    plus = F('плюс') + ' '
    data = cmd.lower().replace(minus, '-').replace(plus, '').split()

    if len(data) == 2 and data[0] == F('до') and utils.is_int(data[1]) and abs(int(data[1])) > 1:
        to_ = int(data[1])
        from_ = 1 if to_ > 0 else -1
    elif len(data) == 4 and utils.is_int(data[1]) and utils.is_int(data[3]) \
            and data[0] == F('от') and data[2] == F('до') and abs(int(data[3]) - int(data[1])) > 0:
        to_, from_ = int(data[3]), int(data[1])
    else:
        return Next

    if abs(to_ - from_) + 1 > 500:
        return Say(F('Это слишком много для меня - считать {} чисел.', abs(to_ - from_) + 1))

    inc_ = 1 if from_ < to_ else -1
    say = [str(x) for x in range(from_, to_ + inc_, inc_)]
    say = [', '.join(say[x: x+max_count]) for x in range(0, len(say), max_count)]
    say.append(F('Я всё сосчитала'))
    return SayLow(phrases=say)


@mod.name(DM, F('Кто я'), F('Получение информации о настройках голосового генератора (только для Яндекса и RHVoice)'))
@mod.phrase([[F('кто ты'), EQ], [F('какая ты'), EQ]])
def who_am_i(self, *_):
    def get_yandex_emo():
        return YANDEX_EMOTION.get(self.cfg.gt('yandex', 'emotion', 'unset'), F('Ошибка'))

    speakers = __tts_selector(self.cfg)
    if speakers is None:
        return Say(F('Не поддерживается для {}', self.cfg.gts('providertts')))

    speaker = self.cfg[self.cfg.gts('providertts')].get('speaker', 'unset')
    emotion = F(' Я очень {}.', get_yandex_emo()) if self.cfg.gts('providertts') == 'yandex' else ''
    return Say(F('Меня зовут {}.{}', speakers.get(speaker, F('Ошибка')), emotion))


@mod.name(DM, F('Теперь я'), F('Изменение характера или голоса голосового генератора (только для Яндекса и RHVoice)'))
@mod.phrase([F('теперь ты'), F('стань')])
def now_i(self, _, cmd):
    speakers = __tts_selector(self.cfg)
    prov = self.cfg.gts('providertts')
    if speakers is None:
        return Say(F('Не поддерживается для {}', prov))

    if cmd:
        cmd = cmd.lower()
        if prov == 'yandex':
            for key, val in YANDEX_EMOTION.items():
                if cmd == val.lower():
                    return __now_i_set_emo(self, key)
        for key, val in speakers.items():
            if cmd == val.lower():
                return __now_i_set_speaker(self, key, self.cfg[prov], speakers, prov == 'yandex')
    return Next


def __tts_selector(cfg):
    if cfg.gts('providertts') in ('rhvoice-rest', 'rhvoice'):
        speakers = RHVOICE_SPEAKER
    elif cfg.gts('providertts') == 'yandex':
        speakers = YANDEX_SPEAKER
    elif cfg.gts('providertts') == 'aws':
        speakers = AWS_SPEAKER
    else:
        return None

    if cfg.gts('providertts') not in cfg:
        cfg[cfg.gts('providertts')] = {}
    return speakers


def __now_i_set_speaker(self, key, prov: dict, speakers: dict, yandex=False):
    if key == prov.get('speaker', 'unset'):
        return Say(F('Я уже {}.', speakers[key]))

    prov['speaker'] = key
    self.cfg.config_save()
    return Say(F(
        'Теперь меня зовут {}, а еще я {}.',
        speakers[key],
        YANDEX_EMOTION.get(self.cfg['yandex'].get('emotion', 'unset'), F('Ошибка'))
        if yandex else F('без характера')
    ))


def __now_i_set_emo(self, key):
    if key == self.cfg.get('emotion', 'unset'):
        return Say(F('Я уже {}.', YANDEX_EMOTION[key]))

    self.cfg['yandex']['emotion'] = key
    self.cfg.config_save()
    return Say(F(
        'Теперь я очень {} {}.',
        YANDEX_EMOTION[key],
        YANDEX_SPEAKER.get(self.cfg['yandex'].get('speaker', 'unset'), F('Ошибка'))
    ))


@mod.name(DM, F('Вики'), F('Поиск в Википедии'))
@mod.phrase([F('расскажи'), F('что ты знаешь'), F('кто такой'), F('что такое'), F('зачем нужен'), F('для чего')])
def wiki(self, _, phrase):
    if not self.code:  # активация фразой
        for k in (F('о'), F('про'), F('в')):
            k += ' '
            if phrase.startswith(k):
                phrase = phrase[len(k):]
                break
        phrase.strip()
    if not phrase:
        return Next
    self.log(F('Ищу в вики о {}', repr(phrase)), logger.INFO)

    try:
        return Say(wikipedia.summary(phrase, sentences=2, chars=1000))
    except wikipedia.exceptions.DisambiguationError as e:
        return Ask(F('Уточните свой вопрос: {}', '. '.join(e.options)))
    except wikipedia.exceptions.PageError:
        return Say(F('Я ничего не знаю о {}.', phrase))


@mod.name(DM, F('Помощь'), F('Справку по модулям (вот эту)'))
@mod.phrase([F('помощь'), F('справка'), F('help'), F('хелп')])
def help_(self, _, phrase):
    def words():
        triggers = [x[0] for x in self.words_by_f_all(f)]
        if not triggers:
            return ''
        return ', '.join(triggers) or F('любую фразу')

    if phrase:
        phrase = phrase.lower()
        if phrase in self.by_name:
            f = self.by_name[phrase]
            module = self.all[f]
            is_del = '' if module['enable'] else F('. Модуль удален')
            msg = F('Модуль {} доступен в режиме {}. Для активации скажите {}. Модуль предоставляет {} {}')
            say = msg.format(phrase, get_mode_say(module['mode']), words(), module['desc'], is_del)
            return Say(say)
        else:
            return Next

    say, deleted = [], []
    for f, module in self.all.items():
        if module['enable']:
            say.append(
                F('Скажите {}. Это активирует {}. Модуль предоставляет {}', words(), module['name'], module['desc'])
            )
        else:
            deleted.append(module['name'])

    if say:
        say.insert(0, F('Всего доступно {} модулей. Вот они:', len(say)))
    if len(deleted):
        say.append(F('Всего {} модулей удалены, это: {}', len(deleted), ', '.join(deleted)))
    say.append(F('Работа модуля помощь завершена.'))
    return SayLow(say)


@mod.name(DM, F('Выход'), F('Завершение работы голосового терминала'))
@mod.phrase([[F('завершение работы'), EQ], [F('завершить работу'), EQ], [F('завершить'), EQ]])
def terminate_(*_):
    return Say(F('Come Along With Me.')), Set(die=5)


@mod.name(DM, F('Перезагрузка'), F('Перезапуск голосового терминала'))
@mod.phrase([[F('Перезагрузка'), EQ], [F('Ребут'), EQ], [F('Рестарт'), EQ], [F('reboot'), EQ]])
def reboot_(*_):
    return Say(F('Терминал перезагрузится через 5... 4... 3... 2... 1...')), Set(die=[5, True])


@mod.name(ANY, F('громкость'), F('Изменение громкости'))
@mod.phrase([F('громкость музыки'), F('громкость')])
def volume(self, trigger, phrase):
    phrase = phrase.replace('%', '')
    if not phrase:
        phrase = None
    elif not phrase.isdigit():
        return Next
    if trigger == F('громкость'):
        self.own.terminal_call('nvolume_say', phrase)
    else:
        self.own.terminal_call('mvolume_say', phrase)


@mod.name(NM, F('Мажордом'), F('Отправку команд на сервер'))
@mod.phrase('')  # Захватит любые фразы
def majordomo(self, _, phrase):
    if not phrase:
        self.log(F('Вы ничего не сказали?'), logger.DEBUG)
        return

    if not self.own.has_subscribers('cmd'):
        if not self.cfg['smarthome']['ip']:
            self.log(F('IP сервера не задан.'), logger.CRIT)
            return Say(F('IP сервера не задан, исправьте это! Мой IP адрес: {}', self.cfg.gts('ip')))
        else:
            msg = F('Невозможно доставить - маршрут не найден')
            self.log(msg, logger.CRIT)
            return Say(msg)

    # FIX: 'Скажи ' -> 'скажи '
    if phrase.startswith(F('Скажи ')):
        phrase = phrase[0].lower() + phrase[1:]

    kwargs = {'qry': phrase}
    if self.model:
        kwargs['username'] = self.cfg.gt('persons', self.model)
    if self.rms:
        kwargs.update(zip(('rms_min', 'rms_max', 'rms_avg'), self.rms))
    self.own.send_notify('cmd', **kwargs)


@mod.name(ANY, F('Терминатор'), F('Информацию что соответствие фразе не найдено'))
@mod.phrase('')
def terminator(_, __, phrase):
    return Say(F('Соответствие фразе не найдено: {}', phrase))
