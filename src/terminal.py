#!/usr/bin/env python3

import os
import queue
import threading
import time
import traceback

import lib.snowboy_training as training_service
import logger
import utils
from languages import LANG_CODE
from languages import STTS as LNG2
from languages import TERMINAL as LNG
from listener import SnowBoy, SnowBoySR
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
        self._wait = threading.Event()

        self.CALL = {
            'reload': self._reload,
            'update': self.own.update,
            'rollback': self.own.manual_rollback,
        }
        self.DATA_CALL = {
            'volume': self._set_volume,
            'volume_q': self._set_volume_quiet,
            'music_volume': self._set_music_volume,
        }
        self.ARGS_CALL = {
            'rec': self._rec_rec,
            'play': self._rec_play,
            'compile': self._rec_compile,
            'del': self._rec_del,
            'send_model': self._send_model,
        }

    def _reload(self):
        if len(self._cfg.path['models_list']) and self.own.max_mic_index != -2:
            if self._cfg.gts('chrome_mode'):
                detected = self._detected_sr
                snowboy = SnowBoySR
            else:
                snowboy = SnowBoy
                detected = self._detected
            self._snowboy = snowboy(self._cfg, detected, self._interrupt_callback, self.own)
        else:
            self._snowboy = None
        self._wait.set()

    def join(self, timeout=None):
        if self._work:
            self._work = False
            self._wait.set()
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
            self._wait.wait(2)
            self._wait.clear()
        else:
            try:
                self._snowboy.start()
            except OSError as e:
                self._work = False
                self.log('Critical error, bye: {}'.format(e), logger.CRIT)
                self.log(traceback.format_exc(), logger.CRIT)
                self.own.die_in(1)
                try:
                    self._snowboy.terminate()
                except OSError:
                    pass
            else:
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
            msg = LNG['get_call'].format(cmd, repr(data)[:300], lvl, int(late))
            if late > self.MAX_LATE:
                self.log(LNG['ignore_call'].format(msg), logger.WARN)
                continue
            else:
                self.log(msg, logger.DEBUG)

            if cmd == 'tts':
                self.own.say(data, lvl=lvl)
            elif cmd == 'ask' and data:
                self._detected_parse(data, self.own.listen(data))
            elif cmd == 'voice' and not data:
                self._detected_parse('', self.own.listen(voice=True))
            elif cmd == 'notify' and data:
                terminal_name = self._cfg.gt('smarthome', 'terminal') or 'mdmTerminal2'
                self._detected_parse(None, '[{}] {}'.format(terminal_name, data))
            elif cmd in self.CALL:
                self.CALL[cmd]()
            elif cmd in self.DATA_CALL:
                self.DATA_CALL[cmd](data)
            elif cmd in self.ARGS_CALL:
                self.ARGS_CALL[cmd](*data)
            else:
                self.log(LNG['err_call'].format(cmd, repr(data)[:300], lvl), logger.ERROR)

    def _rec_rec(self, model, sample):
        # Записываем образец sample для модели model
        if sample not in LNG['rec_nums']:
            self.log('{}: {}'.format(LNG['err_rec_param'], sample), logger.ERROR)
            self.own.say(LNG['err_rec_param'])
            return
        pmdl_name = ''.join(['model', model, self._cfg.path['model_ext']])
        if not self._cfg.is_model_name(pmdl_name):
            self.log('Wrong model filename: {}'.format(repr(pmdl_name)), logger.ERROR)
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

    def _rec_compile(self, model, username):
        samples = []
        for num in ('1', '2', '3'):
            sample_path = os.path.join(self._cfg.path['tmp'], ''.join((model, num, '.wav')))
            if not os.path.isfile(sample_path):
                self.log(LNG['compile_no_file'].format(sample_path), logger.ERROR)
                self.own.say(LNG['compile_no_file'].format(os.path.basename(sample_path)))
            else:
                samples.append(sample_path)
        if len(samples) == 3:
            username = username if len(username) > 1 else None
            self._compile_model(model, samples, username)

    def _rec_del(self, model, _):
        is_del = False
        to_save = False
        pmdl_name = ''.join(['model', model, self._cfg.path['model_ext']])
        pmdl_path = os.path.join(self._cfg.path['models'], pmdl_name)
        if not self._cfg.is_model_name(pmdl_name):
            self.log('Wrong model filename: {}'.format(repr(pmdl_name)), logger.ERROR)
            return

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
        to_save |= self._cfg['models'].pop(pmdl_name, None) is not None
        to_save |= self._cfg['persons'].pop(pmdl_name, None) is not None

        if to_save:
            self._cfg.config_save()
        if is_del:
            self._cfg.models_load()
            self._reload()

    def _compile_model(self, model, samples, username):
        phrase, match_count = self.own.phrase_from_files(samples)
        pmdl_name = ''.join(['model', model, self._cfg.path['model_ext']])
        pmdl_path = os.path.join(self._cfg.path['models'], pmdl_name)
        if not self._cfg.is_model_name(pmdl_name):
            self.log('Wrong model filename: {}'.format(repr(pmdl_name)), logger.ERROR)
            return

        # Начальные параметры для API сноубоя
        params = {key: self._cfg.gt('snowboy', key) for key in ('token', 'name', 'age_group', 'gender', 'microphone')}
        params['language'] = LANG_CODE['ISO']

        if match_count != len(samples):
            msg = LNG['no_consensus'].format(pmdl_name, match_count, len(samples))
            if self._cfg.gt('snowboy', 'clear_models') or self._cfg.gts('chrome_mode'):
                # Не создаем модель если не все фразы идентичны
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
            snowboy = training_service.Training(*samples, params=params)
        except RuntimeError as e:
            self.log(LNG['err_compile_log'].format(pmdl_path, e), logger.ERROR)
            self.own.say(LNG['err_compile_say'].format(model))
            return
        work_time = utils.pretty_time(time.time() - work_time)
        snowboy.save(pmdl_path)

        msg = ', "{}",'.format(phrase) if phrase else ''
        self.log(LNG['compile_ok_log'].format(msg, work_time, pmdl_path), logger.INFO)
        self.own.say(LNG['compile_ok_say'].format(msg, model, work_time))

        self._save_model_data(pmdl_name, username, phrase)

        # Удаляем временные файлы
        for x in samples:
            os.remove(x)

    def _send_model(self, filename, body, username, phrase):
        # Получили модель от сервера (send - это для сервера)
        pmdl_path = os.path.join(self._cfg.path['models'], filename)
        self.log('Model {} received from server: phrase={}, username={}, size={} bytes.'.format(
            repr(filename), repr(phrase), repr(username), len(body)), logger.INFO)
        with open(pmdl_path, 'wb') as fp:
            fp.write(body)
        self._save_model_data(filename, username, phrase)

    def _save_model_data(self, pmdl_name, username, phrase):
        model_data = {'models': {pmdl_name: phrase}}
        if username:
            model_data['persons'] = {pmdl_name: username}
        self._cfg.update_from_dict(model_data)
        self._cfg.models_load()
        self._reload()

    def _set_volume_quiet(self, value):
        self._set_volume(value, True)

    def _set_volume(self, value, quiet=False):
        if value is not None:
            volume = self.own.set_volume(value)
            if volume == -1:
                self.log(LNG['vol_wrong_val'].format(value), logger.WARN)
                if not quiet:
                    self.own.say(LNG['vol_wrong_val'].format(value))
                return
        else:
            volume = self.own.get_volume()
        if value is not None and volume > -1:
            self.own.volume_callback(volume)
        if volume == -2:
            self.log(LNG['vol_not_cfg'], logger.WARN)
            if not quiet:
                self.own.say(LNG['vol_not_cfg'])
        else:
            self.log(LNG['vol_ok'].format(volume))
            if not quiet:
                self.own.say(LNG['vol_ok'].format(volume))

    def _set_music_volume(self, value):
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
            self.own.music_real_volume = vol
        value = self.own.music_real_volume
        self.log(LNG['vol_music_ok'].format(value))
        self.own.say(LNG['vol_music_ok'].format(value))

    def call(self, cmd: str, data='', lvl: int=0, save_time: bool=True):
        if cmd == 'tts' and not lvl:
            if self._cfg.gts('no_background_play'):
                lvl = 2
            else:
                self.own.say(data, lvl=0)
                return
        self._queue.put_nowait((cmd, data, lvl, time.time() if save_time else 0))
        self._wait.set()

    def _detected(self, model: int=0):
        if self._snowboy is not None:
            self._snowboy.terminate()
        self.own.voice_activated_callback()
        phrase = ''
        if not model:
            self.log(LNG['err_call2'], logger.CRIT)
            model_name = None
        else:
            model_name, phrase, msg = self._cfg.model_info_by_id(model)
            self.log(LNG['activate_by'].format(model_name, msg), logger.INFO)
        no_hello = self._cfg.gts('no_hello')
        hello = ''
        if phrase and self.own.sys_say_chance and not no_hello:
            hello = LNG['model_listened'].format(phrase)
        self._speech_recognized_success(hello, self.own.listen(hello, voice=no_hello), model_name)

    def _detected_sr(self, msg: str, model_name: str, model_msg: str, energy_threshold: int):
        if model_msg is None:
            self.log(LNG['wrong_activation'].format(msg, model_name, energy_threshold), logger.DEBUG)
            return
        if self._cfg.gt('listener', 'energy_threshold', 0) < 1:
            energy_threshold = ', energy_threshold={}'.format(energy_threshold)
        else:
            energy_threshold = ''
        self.log(LNG2['recognized'].format(msg, energy_threshold), logger.INFO)
        self.log(LNG['activate_by'].format(model_name, model_msg), logger.INFO)
        if not msg:  # Пустое сообщение
            return
        self._speech_recognized_success(False, msg, model_name)

    def _speech_recognized_success(self, voice, reply, model):
        if voice or reply:
            self.own.speech_recognized_success_callback()
            if self._cfg.gts('alarm_recognized'):
                self.own.play(self._cfg.path['bimp'])
            self._detected_parse(voice, reply, model)

    def _detected_parse(self, voice, reply, model=None):
        caller = False
        if reply or voice:
            while caller is not None:
                reply, caller = self.own.modules_tester(reply, caller, model)
                if caller:
                    reply = self.own.listen(reply or '', voice=not reply)
        if reply:
            self.own.say(reply)
