#!/usr/bin/env python3

import os
import queue
import threading
import time
import traceback

import lib.snowboy_training as training_service
import lib.sr_wrapper as sr
import logger
import utils
from languages import LANG_CODE
from languages import TERMINAL as LNG
from listener import NonBlockListener
from owner import Owner


class MDTerminal(threading.Thread):
    MAX_LATE = 60

    def __init__(self, cfg, log, owner: Owner):
        super().__init__(name='MDTerminal')
        self.log = log
        self._cfg = cfg
        self.own = owner
        self.work = False
        self._listening = True
        self._snowboy = None
        self._old_listener = None
        self._listener_event = owner.registration('listener')
        self._queue = queue.Queue()
        self._wait = threading.Event()

        self.DATA_CALL = {
            'reload': self._reload,
            'volume': self._set_volume,
            'volume_q': self._set_volume_quiet,
            'music_volume': self._set_music_volume,
            'music_volume_q': self._set_music_volume_quiet,
            'listener': self._change_listener,
        }
        self.ARGS_CALL = {
            'rec': self._rec_rec,
            'play': self._rec_play,
            'del': self._rec_del,
            'send_model': self._send_model,
        }
        if self._cfg.detector != 'porcupine':
            self.ARGS_CALL['compile'] = self._rec_compile

    def _mic_tester(self):
        if self.own.max_mic_index == -2:
            return
        if self._test_mic_record():
            self.log('Microphone test: OK', logger.INFO)
        else:
            self.own.max_mic_index = -2
            self.log('Microphone test: STUCK', logger.ERROR)
            self.own.sub_call('default', 'mic_test_error')

    def _test_mic_record(self) -> bool:
        def callback(_, mic, detector):
            with mic as source:
                try:
                    sr.Recognizer().listen1(source=source, vad=detector, timeout=0.8, phrase_time_limit=0.5)
                except sr.WaitTimeoutError:
                    pass
            return None, None
        mic_ = sr.Microphone(device_index=self.own.mic_index)
        listen = NonBlockListener(callback, mic_, self.own.get_vad_detector(mic_, vad_mode='energy'))
        listen.start()
        listen.stop(10)
        return not listen.is_alive()

    def _reload(self, *_):
        if self._listening:
            self._snowboy = self.own.recognition_forever(self._interrupt_check, self._detected_parse)
        else:
            self._snowboy = None
        if bool(self._snowboy) != self._old_listener:
            self._listener_event('on' if self._snowboy else 'off')
            self._old_listener = not self._old_listener
        self._wait.set()

    def join(self, timeout=30):
        self._wait.set()
        super().join(timeout=timeout)

    def start(self):
        self.work = True
        self.log('start', logger.INFO)
        super().start()

    @utils.state_cache(interval=0.1)
    def _no_listen(self):
        return self._cfg['listener']['no_listen_music'] and self.own.music_plays

    def _interrupt_check(self):
        return not self.work or self._queue.qsize() or self._no_listen()

    def run(self):
        self._mic_tester()
        self._reload()
        while self.work:
            self._listen()
            self._external_check()

    def _listen(self):
        if self._snowboy is None:
            self._wait.wait(2)
            self._wait.clear()
        elif self._no_listen():
            time.sleep(0.2)
        else:
            try:
                self._snowboy()
            except OSError as e:
                self.work = False
                self.log('Critical error, bye: {}'.format(e), logger.CRIT)
                self.log(traceback.format_exc(), logger.CRIT)
                self.own.die_in(1)

    def _external_check(self):
        while self._queue.qsize() and self.work:
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
                self._detected_parse(True, self.own.listen(data))
            elif cmd == 'voice' and not data:
                self._detected_parse(False, self.own.listen(voice=True))
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
        save_to = self._cfg.path_to_sample(model, sample)
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
        file = self._cfg.path_to_sample(model, sample)
        if os.path.isfile(file):
            self.own.say(file, is_file=True)
        else:
            self.own.say(LNG['err_play_say'].format('{}.wav'.format(sample)))
            self.log(LNG['err_play_log'].format(file), logger.WARN)

    def _rec_compile(self, model, username):
        samples = []
        for num in ('1', '2', '3'):
            sample_path = self._cfg.path_to_sample(model, num)
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
        to_save = self._cfg['models'].pop(pmdl_name, None) is not None
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
        try:
            self._cfg.remove_samples(model)
        except RuntimeError as e:
            self.log('remove samples \'{}\': {}'.format(model, e), logger.ERROR)

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

    def _set_music_volume_quiet(self, value):
        self._set_music_volume(value, True)

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

    def _set_music_volume(self, value, quiet=False):
        if value is not None:
            try:
                vol = int(value)
                if vol < 0 or vol > 100:
                    raise ValueError('volume must be 0..100')
            except (TypeError, ValueError) as e:
                msg = LNG['vol_wrong_val'].format(value)
                self.log('{}, {}'.format(msg, e), logger.WARN)
                if not quiet:
                    self.own.say(msg)
                return
            self.own.music_real_volume = vol
        value = self.own.music_real_volume
        self.log(LNG['vol_music_ok'].format(value))
        if not quiet:
            self.own.say(LNG['vol_music_ok'].format(value))

    def _change_listener(self, cmd: str):
        cmd = cmd.lower()
        listening = None
        if not cmd:
            listening = not self._listening
        elif cmd in ('off', 'disable'):
            listening = False
        elif cmd in ('on', 'enable'):
            listening = True

        if listening is not None and listening != self._listening:
            self._listening = listening
            self._reload()

    def call(self, cmd: str, data='', lvl: int = 0, save_time: bool = True):
        if cmd == 'tts' and not lvl:
            if self._cfg.gts('no_background_play'):
                lvl = 2
            else:
                self.own.say(data, lvl=0)
                return
        self._queue.put_nowait((cmd, data, lvl, time.time() if save_time else 0))
        self._wait.set()

    def _detected_parse(self, voice: bool, reply: str, model=None):
        caller = False
        self.own.speech_recognized_callback(bool(reply))
        if reply or voice:
            while caller is not None:
                reply, caller = self.own.modules_tester(reply, caller, model)
                if caller:
                    reply = self.own.listen(reply or '', voice=not reply)
                    self.own.speech_recognized_callback(bool(reply))
        if reply:
            self.own.say(reply)
