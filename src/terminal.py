#!/usr/bin/env python3

import os
import queue
import threading
import time
import traceback
from functools import lru_cache

import lib.snowboy_training as training_service
import lib.sr_wrapper as sr
import logger
import utils
from languages import LANG_CODE, F
from lib.audio_utils import reset_vad_caches
from lib.detectors import reset_detector_caches
from lib.volume import clean_volume
from listener import NonBlockListener
from owner import Owner


class MDTerminal(threading.Thread):
    MAX_LATE = 60
    START_SLEEP, MAX_SLEEP = 10, 60 * 30

    def __init__(self, cfg, log, owner: Owner):
        super().__init__(name='MDTerminal')
        self.log = log
        self.cfg = cfg
        self.own = owner
        self.work = False
        self.listening = True
        self._snowboy = None
        self._queue = queue.Queue()
        self._wait = threading.Event()
        self._current_sleep = self.START_SLEEP
        # Что делает терминал, для диагностики зависаний треда
        # 0 - ничего, 1 - слушает микрофон, 2 - тестирут микрофон, 3 - обрабатывает результат, 4 - внешний вызов
        self.stage = 0
        self._sw = _SampleWorker(cfg, log.add('SW'), owner, self._reload)
        self.DATA_CALL = {
            'reload': self._reload,
            'volume': self._set_volume_quiet,  # volume == nvolume
            'nvolume': self._set_volume_quiet,
            'mvolume': self._set_music_volume_quiet,
            'nvolume_say': self._set_volume,
            'mvolume_say' : self._set_music_volume,
            'listener': self._change_listener,
            'callme': self._call_me,
        }
        self.ARGS_CALL = {
            'rec': self._sw.rec_rec,
            'play': self._sw.rec_play,
            'del': self._sw.rec_del,
            'compile': self._sw.rec_compile,
            'send_model': self._sw.send_model,
            'test.record': self._sw.test_record,
            'test.play': self._sw.test_play,
            'test.delete': self._sw.test_delete,
            'test.test': self._sw.test_test,
            'sre': lambda text, rms=None, model=None: self.own.detected_fake(text, rms, model, self._detected_parse),
        }

    def join(self, timeout=30):
        self._wait.set()
        super().join(timeout=timeout)
        self._listener_notify_cached(False)

    def start(self):
        self.work = True
        self.log('start', logger.INFO)
        super().start()

    def run(self):
        self._mic_tester()
        self._reload()
        while self.work:
            self._listen()
            self.stage = 4
            self._external_check()
            self.stage = 0

    def call(self, cmd: str, data='', lvl: int = 0, save_time: bool = True):
        if cmd == 'tts' and not lvl:
            if self.cfg.gts('no_background_play'):
                lvl = 2
            else:
                self.own.say(data, lvl=0)
                return
        self._queue.put_nowait((cmd, data, lvl, time.time() if save_time else 0))
        self._wait.set()

    def diagnostic_msg(self) -> str:
        msg = {
            0: 'No special action - unknown error.',
            1: 'Listening action - microphone broken?',
            2: 'Testing mic action - microphone broken?',
            3: 'Processing recognition result - unknown error.',
            4: 'External call - unknown error.',
        }.get(self.stage, 'INTERNAL ERROR!')
        return '[{}]: {}'.format(self.stage, msg)

    def _sleep_up(self):
        self._wait.wait(self._current_sleep)
        self._wait.clear()
        self._current_sleep = int(self._current_sleep + self._current_sleep * 0.5)
        self._current_sleep = self._current_sleep if self._current_sleep <= self.MAX_SLEEP else self.MAX_SLEEP

    def _sleep_default(self):
        self._current_sleep = self.START_SLEEP

    @utils.state_cache(interval=0.1)
    def _no_listen(self):
        return self.cfg['listener']['no_listen_music'] and self.own.music_plays

    def _interrupt_check(self):
        return not self.work or self._queue.qsize() or self._no_listen()

    def _mic_tester(self):
        if self.own.max_mic_index == -2:
            return
        self.stage = 2
        if self._test_mic_record():
            self.log('Microphone test: OK', logger.INFO)
        else:
            self.own.max_mic_index = -2
            self.log('Microphone test: STUCK', logger.ERROR)
            self.own.sub_call('default', 'mic_test_error')
        self.stage = 0

    def _test_mic_record(self) -> bool:
        def callback(_, mic, detector):
            with mic as source:
                try:
                    sr.Recognizer().listen1(source=source, vad=detector, timeout=0.8, phrase_time_limit=0.5)
                except sr.WaitTimeoutError:
                    pass
            return None
        mic_ = sr.Microphone(device_index=self.own.mic_index)
        listen = NonBlockListener(callback, mic_, self.own.get_vad_detector(mic_, vad_mode='energy'))
        listen.start()
        listen.stop(10)
        return not listen.is_alive()

    def _reload(self, cache_clear=None, *_):
        if cache_clear:
            detector_reconfigure, vad_reconfigure = cache_clear
            if vad_reconfigure:
                reset_vad_caches()
            if detector_reconfigure:
                reset_detector_caches()
                self.cfg.select_hw_detector()
        if self.listening:
            self._snowboy = self.own.recognition_forever(self._interrupt_check, self._detected_parse)
        else:
            self._snowboy = None
        self._listener_notify_cached(bool(self._snowboy))
        self._wait.set()

    def _listen(self):
        if self._snowboy is None:
            self._wait.wait(2)
            self._wait.clear()
        elif self._no_listen():
            time.sleep(0.2)
        else:
            try:
                self.stage = 1
                self._snowboy()
                self.stage = 0
            except utils.RecognitionCrashMessage as e:
                msg = '{} error: {}; Sleeping {} seconds.'.format(self.cfg.detector.NAME, e, self._current_sleep)
                self.log(msg, logger.ERROR)
                self._sleep_up()
            except OSError as e:
                self.work = False
                self.log('Critical error, bye: {}'.format(e), logger.CRIT)
                self.log(traceback.format_exc(), logger.CRIT)
                self.own.die_in(1)
            else:
                self._sleep_default()

    def _external_check(self):
        while self._queue.qsize() and self.work:
            try:
                (cmd, data, lvl, late) = self._queue.get_nowait()
            except queue.Empty:
                self.log(F('Пустая очередь? Impossible!'), logger.ERROR)
                continue
            if late:
                late = time.time() - late
            msg = F('Получено {}:{}, lvl={} опоздание {} секунд.', cmd, repr(data)[:300], lvl, int(late))
            if late > self.MAX_LATE:
                self.log(F('{} Игнорирую.', msg), logger.WARN)
                continue
            else:
                self.log(msg, logger.DEBUG)

            if cmd == 'tts':
                self.own.say(data, lvl=lvl)
            elif cmd == 'ask' and data:
                self._detected_parse(True, *self.own.listen(data))
            elif cmd == 'voice' and not data:
                self._detected_parse(False, *self.own.listen(voice=True))
            elif cmd in self.DATA_CALL:
                self.DATA_CALL[cmd](data)
            elif cmd in self.ARGS_CALL:
                self.ARGS_CALL[cmd](*data)
            else:
                self.log(F('Не верный вызов, WTF? {}:{}, lvl={}', cmd, repr(data)[:300], lvl), logger.ERROR)

    def _set_volume_quiet(self, value):
        self._set_volume(value, True)

    def _set_music_volume_quiet(self, value):
        self._set_music_volume(value, True)

    def _set_volume(self, value, quiet=False):
        if value is not None:
            try:
                value_clean = clean_volume(value)
            except RuntimeError:
                self.log(F('Недопустимое значение: {}', value), logger.WARN)
                if not quiet:
                    self.own.say(F('Недопустимое значение: {}', value))
                return
            volume = self.own.set_volume(value_clean)
        else:
            volume = self.own.get_volume()
        if value is not None and volume > -1:
            self.own.volume_callback(volume)
        if volume == -2:
            self.log(F('Не настроено'), logger.WARN)
            if not quiet:
                self.own.say(F('Не настроено'))
        else:
            self.log(F('Громкость {} процентов', volume))
            if not quiet:
                self.own.say(F('Громкость {} процентов', volume))

    def _set_music_volume(self, value, quiet=False):
        if value is not None:
            try:
                value_clean = clean_volume(value)
            except RuntimeError as e:
                msg = F('Недопустимое значение: {}', value)
                self.log('{}, {}'.format(msg, e), logger.WARN)
                if not quiet:
                    self.own.say(msg)
                return
            self.own.music_real_volume = value_clean
        value = self.own.music_real_volume
        self.log(F('Громкость музыки {} процентов', value))
        if not quiet:
            self.own.say(F('Громкость музыки {} процентов', value))

    def _change_listener(self, cmd: str):
        cmd = cmd.lower()
        if not cmd:
            listening = not self.listening
        elif cmd in ('off', 'disable'):
            listening = False
        elif cmd in ('on', 'enable'):
            listening = True
        else:
            return

        if listening != self.listening:
            self.listening = listening
            self._reload()
        else:
            self._listener_notify_always()

    @lru_cache(maxsize=1)
    def _listener_notify_cached(self, state: bool):
        self._listener_notify(state)

    def _listener_notify_always(self):
        self._listener_notify(bool(self._snowboy))

    def _listener_notify(self, state: bool):
        self.own.sub_call('default', 'listener', 'on' if state else 'off')

    def _call_me(self, data):
        # Для скармливания треду колбеков
        if callable(data):
            try:
                data()
            except Exception as e:
                self.log('callme error: {}'.format(e), logger.ERROR)
        else:
            self.log('Wrong \'callme\' - data must be callable, get {}'.format(type(data)), logger.ERROR)

    def _detected_parse(self, voice: bool, reply: str, rms, model=None):
        # callback, нужно восстановить прошлую стадию
        _stage, self.stage = self.stage, 3
        caller = False
        self.own.speech_recognized_callback(bool(reply))
        if reply or voice:
            while caller is not None:
                reply, caller = self.own.modules_tester(reply, caller, rms, model)
                if caller:
                    reply, rms = self.own.listen(reply or '', voice=not reply)
                    self.own.speech_recognized_callback(bool(reply))
        if reply:
            self.own.say(reply)
        self.stage = _stage


class _SampleWorker:
    def __init__(self, cfg, log, owner: Owner,  reload_cb):
        self.log, self.cfg, self.own = log, cfg, owner
        # Перезагружает терминал, строго в треде самого терминала
        self._reload_cb = reload_cb

    def _send_notify(self, event: str, state: bool) -> None:
        self.own.sub_call('default', event, state)
        return None

    def _is_fake_models(self):
        if self.cfg.detector.FAKE_MODELS:
            self.log('Detector {} use fake models - nope action.'.format(self.cfg.detector.NAME), logger.WARN)
        return self.cfg.detector.FAKE_MODELS

    def rec_rec(self, model, sample):
        # Записываем образец sample для модели model
        if not self.cfg.detector.ALLOW_RECORD:
            msg = F('{} не поддерживает запись образцов.', self.cfg.detector)
            self.log(msg, logger.WARN)
            self.own.say(msg)
            return

        self._send_notify('sample_record', True)
        rec_nums = {'1': F('первого'), '2': F('второго'), '3': F('третьего')}
        if not self.cfg.detector.good_sample(sample):
            self.log('{}: {}'.format(F('Ошибка записи - недопустимый параметр'), sample), logger.ERROR)
            self.own.say(F('Ошибка записи - недопустимый параметр'))
            return self._send_notify('sample_record', False)
        pmdl_name = self.cfg.detector.gen_name('model', model)
        if not self.cfg.detector.is_model_name(pmdl_name):
            self.log('Wrong model filename: {}'.format(repr(pmdl_name)), logger.ERROR)
            return self._send_notify('sample_record', False)

        hello = F('Запись {} образца на 5 секунд начнется после звукового сигнала', rec_nums.get(sample, sample))
        save_to = self.cfg.path_to_sample(model, sample)
        self.log(hello, logger.INFO)
        err = self.own.voice_record(hello=hello, save_to=save_to, convert_rate=16000, convert_width=2)
        if err is None:
            bye = F('Запись {} образца завершена. Вы можете прослушать свою запись.', rec_nums.get(sample, sample))
            self.own.say(bye)
            self.log(bye, logger.INFO)
        else:
            err = F('Ошибка сохранения образца {}: {}', rec_nums.get(sample, sample), err)
            self.log(err, logger.ERROR)
            self.own.say(err)
        self._send_notify('sample_record', False)

    def rec_play(self, model, sample):
        file = self.cfg.path_to_sample(model, sample)
        if os.path.isfile(file):
            self.own.say(file, is_file=True)
        else:
            self.own.say(F('Ошибка воспроизведения - файл {} не найден', '{}.wav'.format(sample)))
            self.log(F('Файл {} не найден.', file), logger.WARN)

    def rec_compile(self, model, username):
        if not self.cfg.detector.ALLOW_TRAINING:
            msg = F('{} не поддерживает тренировку моделей.', self.cfg.detector)
            self.own.say(msg)
            self.log(msg, logger.WARN)
            return

        self._send_notify('model_compile', True)
        samples = []
        samples_miss = []
        for num in range(1, self.cfg.detector.SAMPLES_COUNT + 1):
            sample_path = self.cfg.path_to_sample(model, num)
            if not os.path.isfile(sample_path):
                samples_miss.append('{}.wav'.format(num))
            else:
                samples.append(sample_path)
        if len(samples) >= self.cfg.detector.SAMPLES_TRAINING:
            username = username if len(username) > 1 else None
            self._compile_model(model, samples, username)
        else:
            split, more = 4, ''
            if len(samples_miss) > 4:
                split, more = 3, F(' и еще {}', len(samples_miss) - 3)
            path = os.path.join(self.cfg.path['samples'], model)
            samples_miss = '{}{}'.format(', '.join(samples_miss[:split]), more)
            self.log(F('Ошибка компиляции - файлы {} не найдены в {}.', samples_miss, path), logger.ERROR)
            self.own.say(F('Ошибка компиляции - файлы не найдены.'))
        self._send_notify('model_compile', False)

    def rec_del(self, model, _):
        if self._is_fake_models():
            return
        is_del = False
        pmdl_name = self.cfg.detector.gen_name('model', model)
        pmdl_path = os.path.join(self.cfg.path['models'], pmdl_name)
        if not self.cfg.detector.is_model_name(pmdl_name):
            self.log('Wrong model filename: {}'.format(repr(pmdl_name)), logger.ERROR)
            return

        # remove model file
        if os.path.isfile(pmdl_path):
            try:
                os.remove(pmdl_path)
            except OSError as e:
                msg = F('Ошибка удаление модели номер {}', model)
                self.log('{} [{}]: {}'.format(msg, pmdl_path, e), logger.ERROR)
                self.own.say(msg)
            else:
                is_del = True
                msg = F('Модель номер {} удалена', model)
                self.log('{}: {}'.format(msg, pmdl_path), logger.INFO)
                self.own.say(msg)
        else:
            msg = F('Модель номер {} не найдена', model)
            self.log('{}: {}'.format(msg, pmdl_path), logger.WARN)
            self.own.say(msg)

        # remove model record in config
        to_save = self.cfg['models'].pop(pmdl_name, None) is not None
        to_save |= self.cfg['persons'].pop(pmdl_name, None) is not None

        if to_save:
            self.cfg.config_save()
        if to_save or is_del:
            self.cfg.models_load()
            self._reload_cb()

    def send_model(self, filename, body, username, phrase):
        # Получили модель от сервера (send - это для сервера)
        pmdl_path = os.path.join(self.cfg.path['models'], filename)
        self.log('Model {} received from server: phrase={}, username={}, size={} bytes.'.format(
            repr(filename), repr(phrase), repr(username), len(body)), logger.INFO)
        if self._is_fake_models():
            return
        with open(pmdl_path, 'wb') as fp:
            fp.write(body)
        self._save_model_data(filename, username, phrase)

    def test_record(self, file: str, limit: int, *_, **__):
        if not utils.is_valid_base_filename(file):
            self.log('Pass record, wrong file name: {}'.format(repr(file)), logger.WARN)
            return
        if not os.path.isdir(self.cfg.path['test']):
            try:
                os.makedirs(self.cfg.path['test'])
            except OSError as e:
                self.log('os.makedirs error {}: {}'.format(self.cfg.path['test'], e), logger.ERROR)
                return
        file = self._test_filename_normalization(file)
        save_to = os.path.join(self.cfg.path['test'], file)

        self.log('Start recording {} sec audio after signal...'.format(limit), logger.INFO)
        err = self.own.voice_record(hello=None, save_to=save_to, convert_rate=16000, convert_width=2, limit=limit)
        if err is None:
            self.log('Recording complete and save to {}'.format(file), logger.INFO)
        else:
            self.log('An error occurred while recording: {}'.format(err), logger.WARN)
        self.own.play(self.cfg.path['dong'])

    def test_play(self, files: list, *_, **__):
        for file in self._test_fill_file_paths(files):
            self.own.say(os.path.join(self.cfg.path['test'], file), is_file=True, alarm=True)

    def test_delete(self, files: list, *_, **__):
        files = self._test_fill_file_paths(files)
        if not files:
            return
        deleted = []
        for files in files:
            file_path = os.path.join(self.cfg.path['test'], files)
            try:
                os.remove(file_path)
            except OSError as e:
                self.log('Error deleting {}: {}'.format(file_path, e), logger.ERROR)
            else:
                deleted.append(files)
        count = len(deleted)
        deleted = ', '.join([name for name in deleted])
        self.log('Remove {} files from {}: {}'.format(count, self.cfg.path['test'], deleted), logger.INFO)

    def test_test(self, providers: list, files: list, *_, **__):
        files = self._test_fill_file_paths(files)
        if not files:
            return
        providers = self._test_stt_providers(providers)
        if not providers:
            return
        p_offset = max(len(provider) for provider in providers)
        template = '{:#} [{:>~}]: {}'.replace('#', str(p_offset), 1)
        for name in files:
            result = self.own.multiple_recognition(os.path.join(self.cfg.path['test'], name), providers)
            result.sort(key=lambda x: x.time)
            result = {k.provider: {'time': utils.pretty_time(k.time), 'result': str(k)} for k in result}
            t_offset = max(len(k['time']) for k in result.values())
            head = template.replace('~', str(t_offset), 1)
            self.log('== Multiple recognition for {} =='.format(repr(name)), logger.INFO)
            for provider, data in result.items():
                self.log(head.format(provider, data['time'], repr(data['result'])), logger.INFO)
            self.log('=' * (p_offset + 1), logger.INFO)

    def _test_stt_providers(self, providers: list) -> list:
        if '*' in providers:
            return self.own.stt_providers()
        allow, not_found = [], []
        unique = set()
        for provider in providers:
            if provider in unique:
                continue
            unique.add(provider)
            if self.own.is_stt_provider(provider):
                allow.append(provider)
            else:
                not_found.append(provider)
        if not_found:
            not_found = ', '.join([repr(name) for name in not_found])
            self.log('Unknown STT providers: {}'.format(not_found), logger.DEBUG if allow else logger.WARN)
        return allow

    def _test_fill_file_paths(self, files: list) -> list:
        if not os.path.isdir(self.cfg.path['test']):
            self.log('Test path not exist: \'{}\''.format(self.cfg.path['test']), logger.WARN)
            return []
        if '*' in files:
            # all wav
            return self.cfg.get_all_testfile()
        allow, wrong_name, not_found = [], [], []
        unique = set()
        for file in files:
            if not utils.is_valid_base_filename(file):
                wrong_name.append(file)
                continue
            file = self._test_filename_normalization(file)
            if file in unique:
                continue
            unique.add(file)
            if not os.path.isfile(os.path.join(self.cfg.path['test'], file)):
                not_found.append(file)
            else:
                allow.append(file)
        if wrong_name:
            wrong_name = ', '.join([repr(name) for name in wrong_name])
            self.log('Wrong file names: {}'.format(wrong_name))
        if not_found:
            not_found = ', '.join([name for name in not_found])
            self.log('Files not found: {}'.format(not_found), logger.DEBUG if allow else logger.WARN)
        return allow

    def _test_filename_normalization(self, file: str) -> str:
        file = file.lower()
        return file if os.path.splitext(file)[1] == self.cfg.path['test_ext'] else file + self.cfg.path['test_ext']

    def _compile_model(self, model, samples, username):
        phrase, match_count = self.own.phrase_from_files(samples)
        pmdl_name = self.cfg.detector.gen_name('model', model)
        pmdl_path = os.path.join(self.cfg.path['models'], pmdl_name)
        if not self.cfg.detector.is_model_name(pmdl_name):
            self.log('Wrong model filename: {}'.format(repr(pmdl_name)), logger.ERROR)
            return

        # Начальные параметры для API сноубоя
        params = {key: self.cfg.gt('snowboy', key) for key in ('token', 'name', 'age_group', 'gender', 'microphone')}
        params['language'] = LANG_CODE['ISO']

        if match_count != len(samples):
            msg_ = 'Полный консенсус по модели {} не достигнут [{}/{}]. Советую пересоздать модель.'
            msg = F(msg_, pmdl_name, match_count, len(samples))
            if self.cfg.gt('snowboy', 'clear_models') or self.cfg.gts('chrome_mode'):
                # Не создаем модель если не все фразы идентичны
                self.log(msg, logger.ERROR)
                self.own.say(F('Полный консенсус по модели {} не достигнут. Компиляция отменена.', model))
                return
            else:
                self.log(msg, logger.WARN)
        else:
            params['name'] = phrase.lower()

        self.log(F('Компилирую {}', pmdl_path), logger.INFO)
        work_time = time.time()
        try:
            snowboy = training_service.Training(self.cfg.gt('snowboy', 'url'), *samples, params=params)
        except RuntimeError as e:
            self.log(F('Ошибка компиляции модели {}: {}', pmdl_path, e), logger.ERROR)
            self.own.say(F('Ошибка компиляции модели номер {}', model))
            return
        work_time = utils.pretty_time(time.time() - work_time)
        snowboy.save(pmdl_path)

        msg = ', "{}",'.format(phrase) if phrase else ''
        self.log(F('Модель{} скомпилирована успешно за {}: {}', msg, work_time, pmdl_path), logger.INFO)
        self.own.say(F('Модель{} номер {} скомпилирована успешно за {}', msg, model, work_time), blocking=60)

        self._save_model_data(pmdl_name, username, phrase)

        # Удаляем временные файлы
        try:
            self.cfg.remove_samples(model)
        except RuntimeError as e:
            self.log('remove samples \'{}\': {}'.format(model, e), logger.ERROR)

    def _save_model_data(self, pmdl_name, username, phrase):
        model_data = {'models': {pmdl_name: phrase}}
        if username:
            model_data['persons'] = {pmdl_name: username}
        self.own.settings_from_inside(model_data)
        self.cfg.models_load()
        self._reload_cb()
