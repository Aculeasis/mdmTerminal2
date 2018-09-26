#!/usr/bin/env python3

import urllib.parse
import urllib.request

import wikipedia

import logger
import utils
from modules_manager import EQ
from modules_manager import ModuleWrapper, get_mode_say, get_enable_say
from modules_manager import NM, DM, ANY
from modules_manager import Next, Set, Say, Ask, SayLow

mod = ModuleWrapper()


@mod.name(ANY, 'Блокировка', 'Включение/выключение блокировки терминала')
@mod.phrase(['Блокировка', EQ])
def lock(self, phrase, *_):
    if self.get_one_way is lock:
        if phrase == 'блокировка':
            return Set(one_way=None), Say('Блокировка снята')
        else:
            return Say('Блокировка')
    else:
        return Set(one_way=lock), Say('Блокировка включена')


@mod.name(ANY, 'Отладка', 'Режим настройки и отладки')
@mod.phrase(['Режим разработчика', EQ], NM)
@mod.phrase(['Выход', EQ], DM)
@mod.hardcoded()
def debug(_, phrase, *__):
    if phrase == 'выход':
        return Set(debug=False), Say('Внимание! Выход из режима разработчика')
    elif phrase == 'режим разработчика':
        return Set(debug=True),\
               Say('Внимание! Включён режим разработчика. Для возврата в обычный режим скажите \'выход\'')
    return Next


@mod.name(DM, 'Менеджер', 'Управление модулями')
@mod.phrase(['Активировать везде', 'Активировать', 'Деактивировать', 'удалить', 'восстановить'], DM)
@mod.hardcoded()
def manager(self, phrase, mod_name):
    mod_name = mod_name.lower()
    if mod_name not in self.by_name:
        self.log('Модуль {} не найден'.format(mod_name), logger.INFO)
        return Next
    mod_ = self.by_name[mod_name]
    if self.all[mod_]['hardcoded']:
        return Say('Модуль {} системный, его нельзя настраивать'.format(mod_name))

    modes = {'активировать': NM, 'деактивировать': DM, 'активировать везде': ANY}
    enables = {'удалить': False, 'восстановить': True}
    if phrase in modes:
        if not self.all[mod_]['enable']:
            return Say('Модуль {} удален. Вначале его нужно восстановить'.format(mod_name))
        new_mode = modes[phrase]
        if self.all[mod_]['mode'] == new_mode:
            return Say('Модуль {} уже в режиме {}'.format(mod_name, get_mode_say(new_mode)))
        say = 'Теперь модуль {} доступен в режиме {}'.format(mod_name, get_mode_say(new_mode))
        return Say(say), Set(mod_mode=[mod_, new_mode])
    elif phrase in enables:
        enable = enables[phrase]
        if self.all[mod_]['enable'] == enable:
            return Say('Модуль {} и так {}'.format(mod_name, get_enable_say(enable)))
        say = 'Модуль {} {}'.format(mod_name, get_enable_say(enable))
        return Say(say), Set(mod_enable=[mod_, enable])
    else:
        self.log('Это невозможно, откуда тут {}'.format(phrase), logger.CRIT)
        return Next


@mod.name(DM, 'Скажи', 'Произнесение фразы')
@mod.phrase('Скажи')
def this_say(_, __, phrase):
    return Say(phrase) if phrase else None


@mod.name(ANY, 'Ничего', 'Ничего')
@mod.phrase(['Ничего', EQ])
def this_nothing(*_):
    pass


@mod.name(DM, 'считалка', 'Считалка до числа. Или от числа до числа. Считалка произносит не больше 20 чисел за раз')
@mod.phrase(['сосчитай', 'считай', 'посчитай'])
def counter(_, __, cmd):
    max_count = 20
    data = cmd.lower().split()

    if len(data) == 2 and data[0] == 'до' and utils.is_int(data[1]) and int(data[1]) > 1:
        all_num = int(data[1])
        from_ = 1
        to_ = int(data[1])
        inc_ = 1
    elif len(data) == 4 and utils.is_int(data[1]) and utils.is_int(data[3]) \
            and data[0] == 'от' and data[2] == 'до' and abs(int(data[3]) - int(data[1])) > 0:
        all_num = abs(int(data[3]) - int(data[1]))
        from_ = int(data[1])
        to_ = int(data[3])
        inc_ = 1 if from_ < to_ else -1
    else:
        return Next

    if all_num > 500:
        return Say('Это слишком много для меня - считать {} чисел.'.format(all_num))

    numbers = []
    count = 0
    say = []
    while True:
        numbers.append(str(from_))
        count += 1
        if count == max_count:
            say.append(', '.join(numbers))
            count = 0
            numbers = []
        if from_ == to_:
            break
        from_ += inc_

    if len(numbers):
        say.append(', '.join(numbers))
    say.append('Я всё сосчитала')
    return SayLow(phrases=say)


@mod.name(DM, 'Кто я', 'Получение информации о настройках голосового генератора (только для Яндекса и RHVoice)')
@mod.phrase([['кто ты', EQ], ['какая ты', EQ]])
def who_am_i(self, *_):
    def get_yandex_emo():
        return utils.YANDEX_EMOTION.get(self.cfg['yandex'].get('emotion', 'unset'), 'ошибка')

    speakers = __tts_selector(self)
    if speakers is None:
        return Say('Не поддерживается для {}'.format(self.cfg['providertts']))

    speaker = self.cfg[self.cfg['providertts']].get('speaker', 'unset')
    emotion = ' Я очень {}.'.format(get_yandex_emo()) if self.cfg['providertts'] == 'yandex' else ''
    return Say('Меня зовут {}.{}'.format(speakers.get(speaker, 'Ошибка'), emotion))


@mod.name(DM, 'Теперь я', 'Изменение характера или голоса голосового генератора (только для Яндекса и RHVoice)')
@mod.phrase(['теперь ты', 'стань'])
def now_i(self, _, cmd):
    speakers = __tts_selector(self)
    prov = self.cfg['providertts']
    if speakers is None:
        return Say('Не поддерживается для {}'.format(prov))

    if cmd:
        if prov == 'yandex':
            for key, val in utils.YANDEX_EMOTION.items():
                if cmd == val:
                    return __now_i_set_emo(self, key)
        cmd = cmd[0].upper() + cmd[1:]
        for key, val in speakers.items():
            if cmd == val:
                return __now_i_set_speaker(self, key, self.cfg[prov], speakers, prov == 'yandex')
    return Next


def __tts_selector(self):
    if self.cfg['providertts'] == 'rhvoice-rest':
        speakers = utils.RHVOICE_SPEAKER
    elif self.cfg['providertts'] == 'yandex':
        speakers = utils.YANDEX_SPEAKER
    else:
        return None

    if self.cfg['providertts'] not in self.cfg:
        self.cfg[self.cfg['providertts']] = {}
    return speakers


def __now_i_set_speaker(self, key, prov: dict, speakers: dict, yandex=False):
    if key == prov.get('speaker', 'unset'):
        return Say('Я уже {}.'.format(speakers[key]))

    prov['speaker'] = key
    self.cfg.config_save()
    return Say('Теперь меня зовут {}, а еще я {}.'.format(
        speakers[key],
        utils.YANDEX_EMOTION.get(self.cfg['yandex'].get('emotion', 'unset'), 'Ошибка')
        if yandex else 'без характера'
    ))


def __now_i_set_emo(self, key):
    if key == self.cfg.get('emotion', 'unset'):
        return Say('Я и так {}.'.format(utils.YANDEX_EMOTION[key]))

    self.cfg['yandex']['emotion'] = key
    self.cfg.config_save()
    return Say('Теперь я очень {} {}.'.format(
        utils.YANDEX_EMOTION[key],
        utils.YANDEX_SPEAKER.get(self.cfg['yandex'].get('speaker', 'unset'), 'Ошибка')
    ))


@mod.name(DM, 'Вики', 'Поиск в Википедии')
@mod.phrase(['расскажи', 'что ты знаешь', 'кто такой', 'что такое', 'зачем нужен', 'для чего'])
def wiki(self, _, phrase):
    if not self.code:  # активация фразой
        del_ = ['о ', 'про ', 'в ']
        for k in del_:
            if phrase.startswith(k):
                phrase = phrase[len(k):]
                break
        phrase.strip()
    if not phrase:
        return Next
    self.log('Ищу в вики о \'{}\''.format(phrase), logger.INFO)

    try:
        return Say(wikipedia.summary(phrase, sentences=2, chars=1000))
    except wikipedia.exceptions.DisambiguationError as e:
        return Ask('Уточните свой вопрос: {}'.format('. '.join(e.options)))
    except wikipedia.exceptions.PageError:
        return Say('Я ничего не знаю о {}.'.format(phrase))


@mod.name(DM, 'Помощь', 'Справку по модулям (вот эту)')
@mod.phrase(['помощь', 'справка', 'help', 'хелп'])
def help_(self, _, phrase):
    def words():
        return ', '.join(data[0] or 'любую фразу' for data in self.words_by_f(f))
    if phrase:
        if phrase in self.by_name:
            f = self.by_name[phrase]
            is_del = '' if self.all[f]['enable'] else '. Модуль удален'
            say = 'Модуль {} доступен в режиме {}. Для активации скажите {}. Модуль предоставляет {} {}'.format(
                phrase, get_mode_say(self.all[f]['mode']), words(), self.all[f]['desc'], is_del
            )
            return Say(say)
        else:
            return Next
    say = ['Всего доступно {} модулей. Вот они:']

    deleted = []
    for f in self.all:
        if self.all[f]['enable']:
            say.append('Скажите {}. Это активирует {}. Модуль предоставляет {}'.format(
                words(), self.all[f]['name'], self.all[f]['desc']))
        else:
            deleted.append(self.all[f]['name'])
    say[0] = say[0].format(len(self.all) - len(deleted))
    if len(deleted):
        say.append('Всего {} модулей удалены, это: {}'.format(len(deleted), ', '.join(deleted)))
    say.append('Работа модуля помощь завершена.')
    return SayLow(say)


@mod.name(DM, 'Выход', 'Завершение работы голосового терминала')
@mod.phrase([['Завершение работы', EQ], ['умри', EQ], ['сдохни', EQ]])
def terminate_(*_):
    return Say('Come Along With Me.'), Set(die=5)


@mod.name(DM, 'Перезагрузка', 'Перезапуск голосового терминала')
@mod.phrase([['Перезагрузка', EQ], ['Ребут', EQ], ['Рестарт', EQ], ['reboot', EQ]])
def reboot_(*_):
    return Say('Терминал перезагрузится через 5... 4... 3... 2... 1...'), Set(die=[5, True])


@mod.name(NM, 'Мажордом', 'Отправку команд на сервер Мажордомо')
@mod.phrase('')  # Захватит любые фразы
def majordomo(self, _, phrase):
    if not phrase:
        self.log('Вы ничего не сказали?', logger.DEBUG)
        return

    if not self.cfg['ip_server']:
        self.log('IP сервера majordomo не задан.', logger.CRIT)
        return Say('IP сервера MajorDoMo не задан, исправте это! Мой IP адрес: {}'.format(self.cfg.get('ip', 'ошибка')))

    # FIX: 'Скажи ' -> 'скажи '
    if phrase.startswith('Скажи ', 0, 6):
        phrase = 'с' + phrase[1:]

    url = 'http://{}/command.php?qry={}'.format(self.cfg['ip_server'], urllib.parse.quote_plus(phrase))
    try:
        f = urllib.request.urlopen(url)
    except urllib.request.URLError as err:
        self.log('Ошибка коммуникации с сервером {}: {}'.format(err.errno, err.strerror), logger.ERROR)
        return Say('Ошибка коммуникации с сервером majordomo: {}'.format(err.strerror))
    else:
        f.close()
        self.log('Запрос был успешен: {}'.format(url), logger.DEBUG)


@mod.name(ANY, 'Терминатор', 'Информацию что соответствие фразе не найдено')
@mod.phrase('')
def terminator(_, __, phrase):
    return Say('Соответствие фразе не найдено: {}'.format(phrase))
