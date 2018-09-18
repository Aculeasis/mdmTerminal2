#!/usr/bin/env python3

import os
import threading
import time
import urllib.parse
import urllib.request

import wikipedia

import logger
import player
import stts
import utils
from lib import snowboydecoder

wikipedia.set_lang('ru')


class MDTerminal(threading.Thread):
    def __init__(self, cfg, play_: player.Player, stt: stts.SpeechToText, die_in, log):
        super().__init__(name='MDTerminal')
        self.log = log
        self._cfg = cfg
        self._play = play_
        self._stt = stt
        self.work = False
        self._paused = False
        self._is_paused = False
        self._snowboy = None
        self._callbacks = []
        self.reload()
        self.dbg = DebugMode(cfg, die_in, self._play.say, log)
        self._api = ''
        self._api_cmd = ''
        self._api_time = 0

    def reload(self):
        self.paused(True)
        if len(self._cfg.path['models_list']) and self._stt.max_mic_index != -2:
            self._snowboy = snowboydecoder.HotwordDetector(
                decoder_model=self._cfg.path['models_list'], sensitivity=[self._cfg['sensitivity']]
            )
            self._callbacks = [self._detected for _ in self._cfg.path['models_list']]
        else:
            self._snowboy = None
        self.paused(False)

    def stop(self):
        self.work = False
        self.log('stopping...', logger.DEBUG)
        self.join()
        self.log('stop.', logger.INFO)

    def start(self):
        self.work = True
        super().start()
        self.log('start', logger.INFO)

    def paused(self, paused: bool):
        if self._paused == paused or self._snowboy is None:
            return
        self._paused = paused
        while self._is_paused != paused and self.work:
            time.sleep(0.1)

    def _interrupt_callback(self):
        return not self.work or self._paused or self._api

    def run(self):
        while self.work:
            self._is_paused = self._paused
            if self._paused:
                time.sleep(0.1)
                continue
            self._listen()
            self._external_check()

    def _listen(self):
        if self._snowboy is None:
            time.sleep(0.5)
        else:
            self._snowboy.start(detected_callback=self._callbacks,
                                interrupt_check=self._interrupt_callback,
                                sleep_time=0.03)
            self._snowboy.terminate()

    def _external_check(self):
        if self._api:
            cmd = self._api
            self._api = ''
            txt = self._api_cmd
            time_ = int(time.time()) - self._api_time
            if time_ > 10:
                self.log('Получена {}:{} опоздание {} секунд. Игнорирую.'.format(cmd, txt, time_), logger.WARN)
                return
            else:
                self.log('Получена {}:{} опоздание {} секунд'.format(cmd, txt, time_), logger.DEBUG)
            if self.dbg.dbg():
                self.log('Включен режим разработчика - игнорирую {}'.format(cmd), logger.WARN)
                return
            if cmd == 'ask' and txt:
                self.detected(txt)
            elif cmd == 'voice':
                self._say_reply(voice=True)
            else:
                self.log('Не верный вызов \'{}:{}\''.format(cmd, txt), logger.ERROR)

    def external_detect(self, cmd, txt: str =''):
        self._api = cmd
        self._api_cmd = txt
        self._api_time = int(time.time())

    def _detected(self, model: int=0):
        if not model:
            self.log('Очень странный вызов от сновбоя. Это нужно исправить', logger.CRIT)
        else:
            model -= 1
            if model < len(self._cfg.path['models_list']):
                model_name = os.path.split(self._cfg.path['models_list'][model])[1]
                phrase = self._cfg['models'].get(model_name)
                phrase = '' if not phrase else ': "{}"'.format(phrase)
            else:
                model_name = str(model)
                phrase = ''
            self.log('Голосовая активация по {}{}'.format(model_name, phrase), logger.INFO)
        self.detected()

    def detected(self, hello: str = ''):
        if self._snowboy is not None:
            self._snowboy.terminate()

        reply, dialog = self._say_reply(hello)
        while dialog:
            reply, dialog = self._say_reply(reply, voice=False if reply else True)

        if reply:
            self._play.say(reply, lvl=1)
        self._listen()

    def _say_reply(self, hello: str = '', voice: bool = False) -> [str, bool]:
        cmd = self._stt.listen(hello, deaf=not self.dbg.dbg(), voice=voice)

        result, dialog, success = self.dbg.parse(cmd)
        if success:
            return result, dialog

        if not cmd:
            self.log('Вы ничего не сказали?', logger.DEBUG)
            return '', False

        if not self._cfg['ip_server']:
            self.log('IP сервера majordomo не задан.', logger.CRIT)
            self._play.say('IP сервера MajorDoMo не задан, исправте это! Мой IP адрес: {}'.format(
                self._cfg.get('ip', 'ошибка'))
            )
            return '', False

        # FIX: 'Скажи ' -> 'скажи '
        if cmd.startswith('Скажи ', 0, 6):
            cmd = 'с' + cmd[1:]

        url = 'http://{}/command.php?qry={}'.format(self._cfg['ip_server'], urllib.parse.quote_plus(cmd))
        try:
            f = urllib.request.urlopen(url)
        except urllib.request.URLError as err:
            self.log('Ошибка коммуникации с сервером {}: {}'.format(err.errno, err.strerror), logger.ERROR)
            self._play.say('Ошибка коммуникации с сервером majordomo: {}'.format(err.strerror))
        else:
            f.close()
            self.log('Запрос был успешен: {}'.format(url), logger.DEBUG)
        return '', False


class DebugMode:

    def __init__(self, cfg, die_in, say_, log):
        self.log = log
        self._say_ = say_
        self._cfg = cfg
        self._die_in = die_in
        self.debug = False
        self.lock = False
        self.DBG = {
            'say': ['скажи', self._say],
            'count': [['сосчитай', 'считай', 'посчитай'], self._counted],
            'wiki' : [['расскажи', 'что ты знаешь', 'расскажи',
                       'что ты думаешь', 'кто такой', 'что такое', 'зачем нужен', 'для чего'], self._wiki_parser],
            'get_who': [['кто ты', 'какая ты'], self._get_who],
            'set_mix': [['теперь ты', 'стань', 'ты'], self._set_mix],
            'help': [['помощь', 'справка', 'помоги', 'хэлп', 'хелп'], self._help],
            'stop': [['умри', 'сдохни'], self._stop],
            'exit': ['выход', self._exit]
        }
        self._ask_me = None

    def _low_say(self, msg):
        self._say_(msg, lvl=0)

    def dbg(self) -> bool:
        return self.debug or self.lock

    def parse(self, cmd: str):
        lcmd = cmd.lower().strip()

        if not self.dbg() and lcmd == 'ничего':
            self._ask_me = None
            return '', False, True

        if self.lock:
            if lcmd == 'блокировка':
                self.lock = False
                self._ask_me = None
                return 'Блокировка снята.', False, True
            else:
                return 'Блокировка.', False, True
        elif self._ask_me is None:
            if lcmd == 'блокировка':
                self.lock = True
                return 'Блокировка включена.', False, True
            elif not self.debug and lcmd == 'режим разработчика':
                self.debug = True
                return 'Включён режим разработчика. Для возврата в обычный режим скажите \'выход\'', False, True

        if self.debug:
            return self._dbg_parse(cmd, lcmd)
        return '', False, False

    def _dbg_parse(self, cmd, lcmd):
        if self._ask_me is not None:  # Идет диалог
            ask_me, result = self._ask_me, self._ask_me(cmd)
        else:
            ask_me, result = self._parser(cmd, lcmd)

        to_ask = False
        self._ask_me = None
        if type(result) == str:  # обычный ответ
            if not result:
                result = 'Синтаксическая ошибка.'
            elif result == '.':
                result = ''
        elif type(result) == tuple and len(result) == 2:  # msg, dialog
            if result[1]:  # Разговор с функцией. Следующий вызов с распознанной фразой уйдет в нее же
                self._ask_me = ask_me
                to_ask = True
                result = result[0]
        else:  # Где-то в коде косяк.
            self.log(
                'Странный ответ от функции. Тип: \'{}\', данные: {}'.format(
                    type(result).__name__,
                    str(result)
                ), logger.CRIT
            )
            result = 'Странный ответ от функции.'
        return result, to_ask, True

    def _parser(self, cmd: str, lcmd: str):
        for k in self.DBG:
            if type(self.DBG[k][0]) == list:
                for kk in self.DBG[k][0]:
                    if lcmd.startswith(kk):
                        return self.DBG[k][1], self.DBG[k][1](cmd[len(kk):].lstrip())
            elif lcmd.lower().startswith(self.DBG[k][0], 0, len(self.DBG[k][0])):
                return self.DBG[k][1], self.DBG[k][1](cmd[len(self.DBG[k][0]):].lstrip())
        return None, ''

    def _exit(self, _):
        """выход из режима разработчика"""
        self.debug = False
        return 'Внимание. Выход из режима разработчика.'

    @staticmethod
    def _say(cmd: str):
        """произнесение фразы"""
        return cmd

    def _counted(self, cmd: str):
        """считалку до числа. Или от числа до числа. Считалка произносит не больше 20 чисел за раз"""
        max_count = 20
        data = cmd.lower().strip().split()

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
            return ''
        if all_num > 500:
            return 'Это слишком много для меня - считать {} чисел.'.format(all_num)
        numbers = []
        count = 0
        while True:
            numbers.append(str(from_))
            count += 1
            if count == max_count:
                self._low_say(', '.join(numbers))
                count = 0
                numbers = []
            if from_ == to_:
                break
            from_ += inc_

        if len(numbers):
            self._low_say(', '.join(numbers))
        self._low_say('Я всё сосчитала')
        return '.'

    def _get_who(self, _):
        """получение информации о настройках голосового генератора (только для Яндекса и RHVoice)"""
        def get_yandex_emo():
            return utils.YANDEX_EMOTION.get(self._cfg['yandex'].get('emotion', 'unset'), 'ошибка')
        if self._cfg['providertts'] in ['rhvoice-rest', 'rhvoice']:
            speakers = utils.RHVOICE_SPEAKER
        elif self._cfg['providertts'] == 'yandex':
            speakers = utils.YANDEX_SPEAKER
        else:
            return 'Не поддерживается для {}'.format(self._cfg['providertts'])

        if self._cfg['providertts'] not in self._cfg:
            self._cfg[self._cfg['providertts']] = {}

        speaker = self._cfg[self._cfg['providertts']].get('speaker', 'unset')
        emotion = ' Я очень {}.'.format(get_yandex_emo()) if self._cfg['providertts'] == 'yandex' else ''
        return 'Меня зовут {}.{}'.format(speakers.get(speaker, 'Ошибка'), emotion)

    def _set_mix(self, cmd: str):
        """изменение характера или голоса голосового генератора (только для Яндекса и RHVoice)"""
        cmd = cmd.lower()
        if self._cfg['providertts'] == 'rhvoice-rest':
            speakers = utils.RHVOICE_SPEAKER
        elif self._cfg['providertts'] == 'yandex':
            speakers = utils.YANDEX_SPEAKER
        else:
            return 'Не поддерживается для {}'.format(self._cfg['providertts'])

        if self._cfg['providertts'] not in self._cfg:
            self._cfg[self._cfg['providertts']] = {}

        if cmd:
            if self._cfg['providertts'] == 'yandex':
                for key, val in utils.YANDEX_EMOTION.items():
                    if cmd == val:
                        return self._set_emo(key)
            cmd = cmd[0].upper() + cmd[1:]
            for key, val in speakers.items():
                if cmd == val:
                    return self._set_speaker(key, self._cfg[self._cfg['providertts']], speakers)
        return ''

    def _set_speaker(self, key, prov: dict, speakers: dict):
        if key == prov.get('speaker', 'unset'):
            return 'Я уже {}.'.format(speakers[key])

        prov['speaker'] = key
        self._cfg.config_save()
        return 'Теперь меня зовут {}, а еще я {}.'.format(
            speakers[key],
            utils.YANDEX_EMOTION.get(self._cfg['yandex'].get('emotion', 'unset'), 'Ошибка')
            if prov == 'yandex' else 'без характера'

        )

    def _set_emo(self, key):
        if key == self._cfg.get('emotion', 'unset'):
            return 'Я и так {}.'.format(utils.YANDEX_EMOTION[key])
        self._cfg['yandex']['emotion'] = key
        self._cfg.config_save()
        return 'Теперь я очень {} {}.'.format(
            utils.YANDEX_EMOTION[key],
            utils.YANDEX_SPEAKER.get(self._cfg['yandex'].get('speaker', 'unset'), 'Ошибка')
        )

    def _wiki_parser(self, cmd: str):
        """поиск в Википедии"""
        del_ = ['о ', 'про ', 'в ']
        cmd = cmd.strip()
        for k in del_:
            if cmd.lower().startswith(k, 0, len(k)):
                cmd = cmd[len(k):]
                break
        cmd.strip()
        self.log('Ищу в вики о \'{}\''.format(cmd), logger.INFO)
        if not cmd:
            return ''
        try:
            reply = wikipedia.summary(cmd, sentences=2, chars=1000)
        except wikipedia.exceptions.DisambiguationError as e:
            reply = ('Уточните свой вопрос: {}'.format('. '.join(e.options)), True)
        except wikipedia.exceptions.PageError:
            reply = 'Я ничего не знаю о {}.'.format(cmd)
        return reply

    def _help(self, _):
        """модуль помощи (вот этот)"""
        self._low_say('Всего доступно {} комманд. Вот они:'.format(len(self.DBG)))
        for k in self.DBG:
            if type(self.DBG[k][0]) == list:
                cmd = '\'{}\''.format('. '.join(self.DBG[k][0]))
            elif type(self.DBG[k][0]) == str:
                cmd = '\'{}\''.format(self.DBG[k][0])
            else:
                cmd = '\'Ошибка парсинга\''
            self._low_say('Скажите {}. Это активирует {}.'.format(cmd, self.DBG[k][1].__doc__))
        self._low_say('Работа модуля помощь завершена.')
        return '.'

    def _stop(self, _):
        """завершение работы голосового терминала"""
        self._die_in(5)
        return 'Come Along With Me.'
