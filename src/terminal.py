#!/usr/bin/env python3

import os
import queue
import threading
import time

import lib.snowboy_training as training_service
import logger
import player
from snowboy import SnowBoySR, SnowBoy
import stts
import utils
from languages import STTS as LNG2
from languages import TERMINAL as LNG


class MDTerminal(threading.Thread):
    MAX_LATE = 60

    def __init__(self, cfg, play_: player.Player, stt: stts.SpeechToText, log, handler):
        super().__init__(name='MDTerminal')
        self.log = log
        self._cfg = cfg
        self._play = play_
        self._stt = stt
        self._handler = handler
        self._work = False
        self._snowboy = None
        self._queue = queue.Queue()

    def _reload(self):
        if len(self._cfg.path['models_list']) and self._stt.max_mic_index != -2:
            if self._cfg.gts('chrome_mode'):
                snowboy = SnowBoySR
                detected = self._detected_sr
            else:
                snowboy = SnowBoy
                detected = self._detected
            self._snowboy = snowboy(self._cfg, detected, self._interrupt_callback, self._stt, self._play)
        else:
            self._snowboy = None

    def join(self, timeout=None):
        if self._work:
            self._work = False
            self.log('stopping...', logger.DEBUG)
            super().join()
            self.log('stop.', logger.INFO)

    def start(self):
        self._work = True
        self.log('start', logger.INFO)
        super().start()

    def _interrupt_callback(self):
        return not self._work or self._queue.qsize()

    def run(self):
        self._reload()
        while self._work:
            self._listen()
            self._external_check()

    def _listen(self):
        if self._snowboy is None:
            time.sleep(0.5)
        else:
            self._snowboy.start()
            self._snowboy.terminate()

    def _external_check(self):
        while self._queue.qsize() and self._work:
            try:
                (cmd, data, lvl, late) = self._queue.get_nowait()
            except queue.Empty:
                self.log(LNG['err_queue_empty'], logger.ERROR)
                continue
            if late:
                late = time.time() - late
            msg = LNG['get_call'].format(cmd, data, lvl, int(late))
            if late > self.MAX_LATE:
                self.log(LNG['ignore_call'].format(msg), logger.WARN)
                continue
            else:
                self.log(msg, logger.DEBUG)
            if cmd == 'reload':
                self._reload()
            elif cmd == 'ask' and data:
                self._detected_parse(data, self._stt.listen(data))
            elif cmd == 'voice' and not data:
                self._detected_parse('', self._stt.listen(voice=True))
            elif cmd == 'rec':
                self._rec_rec(*data)
            elif cmd == 'play':
                self._rec_play(*data)
            elif cmd == 'compile':
                self._rec_compile(*data)
            elif cmd == 'tts':
                self._play.say(data, lvl=lvl)
            else:
                self.log(LNG['err_call'].format(cmd, data, lvl), logger.ERROR)

    def _rec_rec(self, model, sample):
        # Записываем образец sample для модели model
        if sample not in LNG['rec_nums']:
            self.log('{}: {}'.format(LNG['err_rec_param'], sample), logger.ERROR)
            self._play.say(LNG['err_rec_param'])
            return

        hello = LNG['rec_hello'].format(LNG['rec_nums'][sample])
        save_to = os.path.join(self._cfg.path['tmp'], model + sample + '.wav')
        self.log(hello, logger.INFO)

        err = self._stt.voice_record(hello=hello, save_to=save_to, convert_rate=16000, convert_width=2)
        if err is None:
            bye = LNG['rec_bye'].format(LNG['rec_nums'][sample])
            self._play.say(bye)
            self.log(bye, logger.INFO)
        else:
            err = LNG['err_rec_save'].format(LNG['rec_nums'][sample], err)
            self.log(err, logger.ERROR)
            self._play.say(err)

    def _rec_play(self, model, sample):
        file_name = ''.join([model, sample, '.wav'])
        file = os.path.join(self._cfg.path['tmp'], file_name)
        if os.path.isfile(file):
            self._play.say(file, is_file=True)
        else:
            self._play.say(LNG['err_play_say'].format(file_name))
            self.log(LNG['err_play_log'].format(file), logger.WARN)

    def _rec_compile(self, model, _):
        models = [os.path.join(self._cfg.path['tmp'], ''.join([model, x, '.wav'])) for x in ['1', '2', '3']]
        miss = False
        for x in models:
            if not os.path.isfile(x):
                miss = True
                self.log(LNG['compile_no_file'].format(x), logger.ERROR)
                self._play.say(LNG['compile_no_file'].format(os.path.basename(x)))
        if not miss:
            self._compile_model(model, models)

    def _compile_model(self, model, models):
        phrase, match_count = self._stt.phrase_from_files(models)
        pmdl_name = ''.join(['model', model, self._cfg.path['model_ext']])
        pmdl_path = os.path.join(self._cfg.path['models'], pmdl_name)

        # Начальные параметры для API сноубоя
        params = {key: self._cfg.gt('snowboy', key) for key in ('token', 'name', 'age_group', 'gender', 'microphone')}
        params['language'] = self._cfg.gts('lang', 'ru')

        if match_count != len(models):
            msg = LNG['no_consensus'].format(pmdl_name, match_count, len(models))
            # Не создаем модель если не все фразы идентичны
            if self._cfg.gt('snowboy', 'clear_models') or self._cfg.gts('chrome_mode'):
                self.log(msg, logger.ERROR)
                self._play.say(LNG['err_no_consensus'].format(model))
                return
            else:
                self.log(msg, logger.WARN)
        else:
            params['name'] = phrase.lower()

        self.log(LNG['compiling'].format(pmdl_path), logger.INFO)
        work_time = time.time()
        try:
            snowboy = training_service.Training(*models, params=params)
        except RuntimeError as e:
            self.log(LNG['err_compile_log'].format(pmdl_path, e), logger.ERROR)
            self._play.say(LNG['err_compile_say'].format(model))
            return
        work_time = utils.pretty_time(time.time() - work_time)
        snowboy.save(pmdl_path)

        msg = ', "{}",'.format(phrase) if phrase else ''
        self.log(LNG['compile_ok_log'].format(msg, work_time, pmdl_path), logger.INFO)
        self._play.say(LNG['compile_ok_say'].format(msg, model, work_time))

        self._cfg.update_from_dict({'models': {pmdl_name: phrase}})
        self._cfg.models_load()
        self._reload()
        # Удаляем временные файлы
        for x in models:
            os.remove(x)

    def call(self, cmd: str, data='', lvl: int=0, save_time: bool=True):
        if cmd == 'tts' and not lvl:
            if self._cfg.gts('no_background_play'):
                lvl = 2
            else:
                self._play.say(data, lvl=0)
                return
        self._queue.put_nowait((cmd, data, lvl, time.time() if save_time else 0))

    def _detected(self, model: int=0):
        if self._snowboy is not None:
            self._snowboy.terminate()
        phrase = ''
        if not model:
            self.log(LNG['err_call2'], logger.CRIT)
        else:
            model_name, phrase, msg = self._cfg.model_info_by_id(model)
            self.log(LNG['activate_by'].format(model_name, msg), logger.INFO)
        no_hello = self._cfg.gts('no_hello', 0)
        hello = ''
        if phrase and self._stt.sys_say.chance and not no_hello:
            hello = LNG['model_listened'].format(phrase)
        self._detected_parse(hello, self._stt.listen(hello, voice=no_hello))

    def _detected_sr(self, msg: str, model_name: str, model_msg: str, energy_threshold: int):
        if model_msg is None:
            self.log(LNG['wrong_activation'].format(msg, model_name), logger.DEBUG)
            return
        if self._cfg.gts('energy_threshold', 0) < 1:
            energy_threshold = ', energy_threshold={}'.format(energy_threshold)
        else:
            energy_threshold = ''
        self.log(LNG2['recognized'].format(msg, energy_threshold), logger.INFO)
        self.log(LNG['activate_by'].format(model_name, model_msg), logger.INFO)
        if not msg:  # Пустое сообщение
            return
        if self._cfg.gts('alarmkwactivated'):
            self._play.play(self._cfg.path['ding'])
        self._detected_parse(False, msg)

    def _detected_parse(self, voice, reply):
        caller = False
        if reply or voice:
            while caller is not None:
                reply, caller = self._handler(reply, caller)
                if caller:
                    reply = self._stt.listen(reply or '', voice=not reply)
        if reply:
            self._play.say(reply)
