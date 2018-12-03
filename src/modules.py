#!/usr/bin/env python3

import wikipedia

import logger
import utils
from languages import MODULES as LNG
from languages import YANDEX_SPEAKER, YANDEX_EMOTION, RHVOICE_SPEAKER
from modules_manager import EQ
from modules_manager import ModuleWrapper, get_mode_say, get_enable_say
from modules_manager import NM, DM, ANY
from modules_manager import Next, Set, Say, Ask, SayLow

wikipedia.set_lang('ru')
mod = ModuleWrapper()


@mod.name(ANY, LNG['lock_name'], LNG['lock_dsc'])
@mod.phrase([LNG['lock_phrase_lock'], EQ])
def lock(self, phrase, *_):
    if self.get_one_way is lock:
        if phrase == LNG['lock_phrase_lock']:
            return Set(one_way=None), Say(LNG['lock_say_unlock'])
        else:
            return Say(LNG['lock_phrase_lock'])
    else:
        return Set(one_way=lock), Say(LNG['lock_say_lock'])


@mod.name(ANY, LNG['debug_name'], LNG['debug_dsc'])
@mod.phrase([LNG['debug_phrase_enter'], EQ], NM)
@mod.phrase([LNG['debug_phrase_exit'], EQ], DM)
@mod.hardcoded()
def debug(_, phrase, *__):
    if phrase == LNG['debug_phrase_exit']:
        return Set(debug=False), Say(LNG['debug_say_exit'])
    elif phrase == LNG['debug_phrase_enter']:
        return Set(debug=True), Say(LNG['debug_say_enter'])
    return Next


@mod.name(DM, LNG['mm_name'], LNG['mm_desc'])
@mod.phrase([LNG['mm_act_all'], LNG['mm_act'], LNG['mm_uact'], LNG['mm_del'], LNG['mm_rec']], DM)
@mod.hardcoded()
def manager(self, phrase, mod_name):
    mod_name = mod_name.lower()
    if mod_name not in self.by_name:
        self.log(LNG['mm_no_mod'].format(mod_name), logger.INFO)
        return Next
    mod_ = self.by_name[mod_name]
    if self.all[mod_]['hardcoded']:
        return Say(LNG['mm_sys_mod'].format(mod_name))

    modes = {LNG['mm_act']: NM, LNG['mm_uact']: DM, LNG['mm_act_all']: ANY}
    enables = {LNG['mm_del']: False, LNG['mm_rec']: True}
    if phrase in modes:
        if not self.all[mod_]['enable']:
            return Say(LNG['mm_must_rec'].format(mod_name))
        new_mode = modes[phrase]
        if self.all[mod_]['mode'] == new_mode:
            return Say(LNG['mm_already'].format(mod_name, get_mode_say(new_mode)))
        say = LNG['mm_now'].format(mod_name, get_mode_say(new_mode))
        return Say(say), Set(mod_mode=[mod_, new_mode])
    elif phrase in enables:
        enable = enables[phrase]
        if self.all[mod_]['enable'] == enable:
            return Say(LNG['mm_already2'].format(mod_name, get_enable_say(enable)))
        say = LNG['mm_mod'].format(mod_name, get_enable_say(enable))
        return Say(say), Set(mod_enable=[mod_, enable])
    else:
        self.log(LNG['err_mm'].format(phrase), logger.CRIT)
        return Next


@mod.name(DM, LNG['say_name'], LNG['say_desc'])
@mod.phrase(LNG['say_name'])
def this_say(_, __, phrase):
    return Say(phrase) if phrase else None


@mod.name(ANY, LNG['nothing_all'], LNG['nothing_all'])
@mod.phrase([LNG['nothing_all'], EQ])
def this_nothing(*_):
    pass


@mod.name(DM, LNG['count_name'], LNG['count_desc'])
@mod.phrase(LNG['count_phrase_list'])
def counter(_, __, cmd):
    max_count = 20
    data = cmd.lower().split()

    if len(data) == 2 and data[0] == LNG['count_to'] and utils.is_int(data[1]) and int(data[1]) > 1:
        all_num = int(data[1])
        from_ = 1
        to_ = int(data[1])
        inc_ = 1
    elif len(data) == 4 and utils.is_int(data[1]) and utils.is_int(data[3]) \
            and data[0] == LNG['count_from'] and data[2] == LNG['count_to'] and abs(int(data[3]) - int(data[1])) > 0:
        all_num = abs(int(data[3]) - int(data[1]))
        from_ = int(data[1])
        to_ = int(data[3])
        inc_ = 1 if from_ < to_ else -1
    else:
        return Next

    if all_num > 500:
        return Say(LNG['count_to_long'].format(all_num))

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
    say.append(LNG['count_complete'])
    return SayLow(phrases=say)


@mod.name(DM, LNG['who_name'], LNG['who_desc'])
@mod.phrase([[LNG['who_ph_1'], EQ], [LNG['who_ph_2'], EQ]])
def who_am_i(self, *_):
    def get_yandex_emo():
        return YANDEX_EMOTION.get(self.cfg['yandex'].get('emotion', 'unset'), LNG['error'])

    speakers = __tts_selector(self.cfg)
    if speakers is None:
        return Say(LNG['who_now_no_support'].format(self.cfg.gts('providertts')))

    speaker = self.cfg[self.cfg.gts('providertts')].get('speaker', 'unset')
    emotion = LNG['who_my_emo'].format(get_yandex_emo()) if self.cfg.gts('providertts') == 'yandex' else ''
    return Say(LNG['who_my_name'].format(speakers.get(speaker, LNG['error']), emotion))


@mod.name(DM, LNG['now_name'], LNG['now_desc'])
@mod.phrase(LNG['now_phrases_list'])
def now_i(self, _, cmd):
    speakers = __tts_selector(self.cfg)
    prov = self.cfg.gts('providertts')
    if speakers is None:
        return Say(LNG['who_now_no_support'].format(prov))

    if cmd:
        if prov == 'yandex':
            for key, val in YANDEX_EMOTION.items():
                if cmd == val:
                    return __now_i_set_emo(self, key)
        cmd = cmd[0].upper() + cmd[1:]
        for key, val in speakers.items():
            if cmd == val:
                return __now_i_set_speaker(self, key, self.cfg[prov], speakers, prov == 'yandex')
    return Next


def __tts_selector(cfg):
    if cfg.gts('providertts') == 'rhvoice-rest':
        speakers = RHVOICE_SPEAKER
    elif cfg.gts('providertts') == 'yandex':
        speakers = YANDEX_SPEAKER
    else:
        return None

    if cfg.gts('providertts') not in cfg:
        cfg[cfg.gts('providertts')] = {}
    return speakers


def __now_i_set_speaker(self, key, prov: dict, speakers: dict, yandex=False):
    if key == prov.get('speaker', 'unset'):
        return Say(LNG['now_already'].format(speakers[key]))

    prov['speaker'] = key
    self.cfg.config_save()
    return Say(LNG['now_i_now'].format(
        speakers[key],
        YANDEX_EMOTION.get(self.cfg['yandex'].get('emotion', 'unset'), LNG['error'])
        if yandex else LNG['now_no_character']
    ))


def __now_i_set_emo(self, key):
    if key == self.cfg.get('emotion', 'unset'):
        return Say(LNG['now_already'].format(YANDEX_EMOTION[key]))

    self.cfg['yandex']['emotion'] = key
    self.cfg.config_save()
    return Say(LNG['now_i_very'].format(
        YANDEX_EMOTION[key],
        YANDEX_SPEAKER.get(self.cfg['yandex'].get('speaker', 'unset'), LNG['error'])
    ))


@mod.name(DM, LNG['wiki_name'], LNG['wiki_desc'])
@mod.phrase(LNG['wiki_phrases_list'])
def wiki(self, _, phrase):
    if not self.code:  # активация фразой
        for k in LNG['wiki_rm_pretext_list']:
            if phrase.startswith(k):
                phrase = phrase[len(k):]
                break
        phrase.strip()
    if not phrase:
        return Next
    self.log(LNG['wiki_find_of'].format(phrase), logger.INFO)

    try:
        return Say(wikipedia.summary(phrase, sentences=2, chars=1000))
    except wikipedia.exceptions.DisambiguationError as e:
        return Ask(LNG['wiki_ask'].format('. '.join(e.options)))
    except wikipedia.exceptions.PageError:
        return Say(LNG['wiki_not_know'].format(phrase))


@mod.name(DM, LNG['help_name'], LNG['help_desc'])
@mod.phrase(LNG['help_phrases_list'])
def help_(self, _, phrase):
    def words():
        return ', '.join(data[0] for data in self.words_by_f(f)) or LNG['help_any_phrase']
    if phrase:
        phrase = phrase.lower()
        if phrase in self.by_name:
            f = self.by_name[phrase]
            is_del = '' if self.all[f]['enable'] else LNG['help_mod_deleted']
            say = LNG['help_mod_full'].format(
                phrase, get_mode_say(self.all[f]['mode']), words(), self.all[f]['desc'], is_del
            )
            return Say(say)
        else:
            return Next
    say = [LNG['help_mod_header']]

    deleted = []
    for f in self.all:
        if self.all[f]['enable']:
            say.append(LNG['help_mod_line'].format(words(), self.all[f]['name'], self.all[f]['desc']))
        else:
            deleted.append(self.all[f]['name'])
    say[0] = say[0].format(len(self.all) - len(deleted))
    if len(deleted):
        say.append(LNG['help_mod_del_header'].format(len(deleted), ', '.join(deleted)))
    say.append(LNG['help_bye'])
    return SayLow(say)


@mod.name(DM, LNG['term_name'], LNG['term_desc'])
@mod.phrase([[LNG['term_phs_list_3'][0], EQ], [LNG['term_phs_list_3'][1], EQ], [LNG['term_phs_list_3'][2], EQ]])
def terminate_(*_):
    return Say(LNG['term_bye']), Set(die=5)


@mod.name(DM, LNG['rbt_name'], LNG['rbt_dsc'])
@mod.phrase([[LNG['rbt_ph_4'][0], EQ], [LNG['rbt_ph_4'][1], EQ], [LNG['rbt_ph_4'][2], EQ], [LNG['rbt_ph_4'][3], EQ]])
def reboot_(*_):
    return Say(LNG['rbt_bye']), Set(die=[5, True])


@mod.name(ANY, LNG['volume_name'], LNG['volume_desc'])
@mod.phrase(LNG['volume_name'])
def volume(self, _, phrase):
    if phrase.isdigit():
        self.terminal_call('volume', phrase)
    else:
        return Next


@mod.name(NM, LNG['mjd_name'], LNG['mjd_desc'])
@mod.phrase('')  # Захватит любые фразы
def majordomo(self, _, phrase):
    if not phrase:
        self.log(LNG['mjd_no_say'], logger.DEBUG)
        return

    if not self.mjd.ip_set:
        self.log(LNG['mjd_no_ip_log'], logger.CRIT)
        return Say(LNG['mjd_no_ip_say'].format(self.cfg.get('ip', LNG['error'])))

    # FIX: 'Скажи ' -> 'скажи '
    if phrase.startswith(LNG['mjd_rep_say'], 0, LNG['mjd_rep_say_len']):
        phrase = LNG['mjd_rep_say_s'] + phrase[1:]

    try:
        self.log(LNG['mjd_ok'].format(self.mjd.send(phrase)), logger.DEBUG)
    except RuntimeError as e:
        self.log(LNG['err_mjd'].format(e), logger.ERROR)
        return Say(LNG['err_mjd'].format(''))


@mod.name(ANY, LNG['terminator_name'], LNG['terminator_desc'])
@mod.phrase('')
def terminator(_, __, phrase):
    return Say(LNG['terminator_say'].format(phrase))
