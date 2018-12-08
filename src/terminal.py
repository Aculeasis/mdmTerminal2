#!/usr/bin/env python3

import os
import queue
import threading
import time

import lib.snowboy_training as training_service
import logger
import utils
from languages import LANG_CODE
from languages import STTS as LNG2
from languages import TERMINAL as LNG
from lib import volume
from lib.snowboy import SnowBoySR, SnowBoySR2, SnowBoySR3, SnowBoy
from owner import Owner


class MDTerminal(threading.Thread):
    MAX_LATE = 60

    def __init__(self, cfg, log, owner: Owner):
        super().__init__(name='MDTerminal')
        self.log = log
        self._cfg = cfg
        self.own = owner
        self._work = False
        self._snowboy = None
        self._queue = queue.Queue()

    def _reload(self):
        if len(self._cfg.path['models_list']) and self.own.max_mic_index != -2:
            detected = self._detected_sr
            if self._cfg.gts('chrome_mode') == 1:
                snowboy = SnowBoySR
            elif self._cfg.gts('chrome_mode') == 2:
                snowboy = SnowBoySR2
            elif self._cfg.gts('chrome_mode') == 3:
                snowboy = SnowBoySR3
            else:
                snowboy = SnowBoy
                detected = self._detected
            self._snowboy = snowboy(self._cfg, detected, self._interrupt_callback, self.own)
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
                self._detected_parse(data, self.own.listen(data))
            elif cmd == 'voice' and not data:
                self._detected_parse('', self.own.listen(voice=True))
            elif cmd == 'rec':
                self._rec_rec(*data)
            elif cmd == 'play':
                self._rec_play(*data)
            elif cmd == 'compile':
                self._rec_compile(*data)
            elif cmd == 'del':
                self._rec_del(*data)
            elif cmd == 'volume':
                self._set_volume(data)
            elif cmd == 'mpd_volume':
                self._set_mpd_volume(data)
            elif cmd == 'tts':
                self.own.say(data, lvl=lvl)
            elif cmd == 'update':
                self.own.update()
            elif cmd == 'rollback':
                self.own.manual_rollback()
            elif cmd == 'notify' and data:
                terminal_name = self._cfg.gt('majordomo', 'terminal') or 'mdmTerminal2'
                self._detected_parse(None, '[{}] {}'.format(terminal_name, data))
            else:
                self.log(LNG['err_call'].format(cmd, data, lvl), logger.ERROR)

    def _rec_rec(self, model, sample):
        # Записываем образец sample для модели model
        if sample not in LNG['rec_nums']:
            self.log('{}: {}'.format(LNG['err_rec_param'], sample), logger.ERROR)
            self.own.say(LNG['err_rec_param'])
            return

        hello = LNG['rec_hello'].format(LNG['rec_nums'][sample])
        save_to = os.path.join(self._cfg.path['tmp'], model + sample + '.wav')
        self.log(hello, logger.INFO)
        err = self.own.voice_record(hello=hello, save_to=save_to, convert_rate=16000, convert_width=2)
        if err is None:
            bye = LNG['rec_bye'].format(LNG['rec_nums'][sample])
            self.own.say(bye)
            self.log(bye, logger.INFO)
        else:
            err = LNG['err_rec_save'].format(LNG['rec_nums'][sample], err)
            self.log(err, logger.ERROR)
            self.own.say(err)

    def _rec_play(self, model, sample):
        file_name = ''.join([model, sample, '.wav'])
        file = os.path.join(self._cfg.path['tmp'], file_name)
        if os.path.isfile(file):
            self.own.say(file, is_file=True)
        else:
            self.own.say(LNG['err_play_say'].format(file_name))
            self.log(LNG['err_play_log'].format(file), logger.WARN)

    def _rec_compile(self, model, _):
        models = [os.path.join(self._cfg.path['tmp'], ''.join([model, x, '.wav'])) for x in ['1', '2', '3']]
        miss = False
        for x in models:
            if not os.path.isfile(x):
                miss = True
                self.log(LNG['compile_no_file'].format(x), logger.ERROR)
                self.own.say(LNG['compile_no_file'].format(os.path.basename(x)))
        if not miss:
            self._compile_model(model, models)

    def _rec_del(self, model, _):
        is_del = False
        pmdl_name = ''.join(['model', model, self._cfg.path['model_ext']])
        pmdl_path = os.path.join(self._cfg.path['models'], pmdl_name)

        # remove model file
        if os.path.isfile(pmdl_path):
            try:
                os.remove(pmdl_path)
            except OSError as e:
                msg = LNG['err_del'].format(model)
                self.log('{} [{}]: {}'.format(msg, pmdl_path, e), logger.ERROR)
                self.own.say(msg)
            else:
                is_del = True
                msg = LNG['del_ok'].format(model)
                self.log('{}: {}'.format(msg, pmdl_path), logger.INFO)
                self.own.say(msg)
        else:
            msg = LNG['del_not_found'].format(model)
            self.log('{}: {}'.format(msg, pmdl_path), logger.WARN)
            self.own.say(msg)

        # remove model record in config
        if pmdl_name in self._cfg['models']:
            del self._cfg['models'][pmdl_name]
            self._cfg.config_save()

        if is_del:
            self._cfg.models_load()
            self._reload()

    def _compile_model(self, model, models):
        phrase, match_count = self.own.phrase_from_files(models)
        pmdl_name = ''.join(['model', model, self._cfg.path['model_ext']])
        pmdl_path = os.path.join(self._cfg.path['models'], pmdl_name)

        # Начальные параметры для API сноубоя
        params = {key: self._cfg.gt('snowboy', key) for key in ('token', 'name', 'age_group', 'gender', 'microphone')}
        params['language'] = LANG_CODE['ISO']

        if match_count != len(models):
            msg = LNG['no_consensus'].format(pmdl_name, match_count, len(models))
            # Не создаем модель если не все фразы идентичны
            if self._cfg.gt('snowboy', 'clear_models') or self._cfg.gts('chrome_mode'):
                self.log(msg, logger.ERROR)
                self.own.say(LNG['err_no_consensus'].format(model))
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
            self.own.say(LNG['err_compile_say'].format(model))
            return
        work_time = utils.pretty_time(time.time() - work_time)
        snowboy.save(pmdl_path)

        msg = ', "{}",'.format(phrase) if phrase else ''
        self.log(LNG['compile_ok_log'].format(msg, work_time, pmdl_path), logger.INFO)
        self.own.say(LNG['compile_ok_say'].format(msg, model, work_time))

        self._cfg.update_from_dict({'models': {pmdl_name: phrase}})
        self._cfg.models_load()
        self._reload()
        # Удаляем временные файлы
        for x in models:
            os.remove(x)

    def _set_volume(self, value):
        control = self._cfg.gt('volume', 'line_out')
        if not control or control == volume.UNDEFINED:
            self.log(LNG['vol_not_cfg'], logger.WARN)
            self.own.say(LNG['vol_not_cfg'])
            return
        if value is not None:
            try:
                value = volume.set_volume(value, control)
            except RuntimeError as e:
                msg = LNG['vol_wrong_val'].format(value)
                self.log('{}, {}'.format(msg, e), logger.WARN)
                self.own.say(msg)
                return
            else:
                self.own.volume_callback(value)
        else:
            value = volume.get_volume(control)
        self.log(LNG['vol_ok'].format(value))
        self.own.say(LNG['vol_ok'].format(value))

    def _set_mpd_volume(self, value):
        if value is not None:
            try:
                vol = int(value)
                if vol < 0 or vol > 100:
                    raise ValueError('volume must be 0..100')
            except (TypeError, ValueError) as e:
                msg = LNG['vol_wrong_val'].format(value)
                self.log('{}, {}'.format(msg, e), logger.WARN)
                self.own.say(msg)
                return
            self.own.mpd_real_volume = vol
        value = self.own.mpd_real_volume
        self.log(LNG['vol_mpd_ok'].format(value))
        self.own.say(LNG['vol_mpd_ok'].format(value))

    def call(self, cmd: str, data='', lvl: int=0, save_time: bool=True):
        if cmd == 'tts' and not lvl:
            if self._cfg.gts('no_background_play'):
                lvl = 2
            else:
                self.own.say(data, lvl=0)
                return
        self._queue.put_nowait((cmd, data, lvl, time.time() if save_time else 0))

    def _detected(self, model: int=0):
        if self._snowboy is not None:
            self._snowboy.terminate()
        self.own.voice_activated_callback()
        phrase = ''
        if not model:
            self.log(LNG['err_call2'], logger.CRIT)
        else:
            model_name, phrase, msg = self._cfg.model_info_by_id(model)
            self.log(LNG['activate_by'].format(model_name, msg), logger.INFO)
        no_hello = self._cfg.gts('no_hello', 0)
        hello = ''
        if phrase and self.own.sys_say_chance and not no_hello:
            hello = LNG['model_listened'].format(phrase)
        self._detected_parse(hello, self.own.listen(hello, voice=no_hello))

    def _detected_sr(self, msg: str, model_name: str, model_msg: str, energy_threshold: int):
        if model_msg is None:
            self.log(LNG['wrong_activation'].format(msg, model_name, energy_threshold), logger.DEBUG)
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
            self.own.play(self._cfg.path['ding'])
        self._detected_parse(False, msg)

    def _detected_parse(self, voice, reply):
        caller = False
        if reply or voice:
            while caller is not None:
                reply, caller = self.own.modules_tester(reply, caller)
                if caller:
                    reply = self.own.listen(reply or '', voice=not reply)
        if reply:
            self.own.say(reply)
