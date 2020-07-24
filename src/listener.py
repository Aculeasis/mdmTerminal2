#!/usr/bin/env python3

import threading
import time

import logger
from languages import F
from lib import sr_wrapper as sr
from lib.audio_utils import ModuleLoader
from lib.audio_utils import SnowboyHWD, WebRTCVAD, APMVAD, get_hot_word_detector
from owner import Owner
from utils import recognition_msg


class Listener:
    def __init__(self, cfg, log, owner: Owner, *_, **__):
        self.cfg = cfg
        self.log = log
        self.own = owner

    def _print_loading_errors(self):
        for msg in ModuleLoader().extract_errors():
            self.log(msg, logger.CRIT)

    def recognition_forever(self, interrupt_check: callable, callback: callable):
        if not self.cfg.detector.NAME:
            self.log('Wake word detection don\'t work on this system: {}'.format(self.cfg.platform), logger.WARN)
        elif self.cfg.path['models_list'] and self.own.max_mic_index != -2:
            if ModuleLoader().is_loaded(self.cfg.detector.NAME):
                return lambda: self._smart_listen(interrupt_check, callback)
            else:
                self._print_loading_errors()
        return None

    def _smart_listen(self, interrupt_check, callback):
        r = sr.Recognizer(self.own.record_callback, self.cfg.gt('listener', 'silent_multiplier'))
        adata = None
        while not interrupt_check():
            chrome_mode = self.cfg.gts('chrome_mode')
            with sr.Microphone(device_index=self.own.mic_index) as source:
                vad, noising = self._get_vad_detector(source, self.cfg.gt('listener', 'vad_chrome') or None)
                if not isinstance(vad, SnowboyHWD):
                    hw_detector = self._get_hw_detector(source.SAMPLE_WIDTH, source.SAMPLE_RATE, vad)
                else:
                    hw_detector = vad
                try:
                    model_id, frames, elapsed_time = sr.wait_detection(source, hw_detector, interrupt_check, noising)
                except sr.Interrupted:
                    continue
                except RuntimeError:
                    return
                model_name, phrase, msg = self.cfg.model_info_by_id(model_id)
                if chrome_mode:
                    if not phrase:
                        # модель без триггера?
                        self._detected_sr(msg or 'unset trigger', model_name, None, None)
                        continue
                    if self.cfg.gts('chrome_choke'):
                        self.own.full_quiet()
                    try:
                        adata = self._listen(r, source, vad, frames=frames, hw_time=elapsed_time)
                    except (sr.WaitTimeoutError, RuntimeError):
                        continue
            if chrome_mode:
                self._adata_parse(adata, model_name, phrase, vad, callback)
            else:
                hw_detector.reset()
                self._detected(model_name, phrase, msg, callback)

    def _adata_parse(self, adata, model_name: str, phrases: str, vad, callback):
        if self.cfg.gts('chrome_alarmstt'):
            self.own.play(self.cfg.path['dong'])
        msg = self.own.voice_recognition(adata)
        if not msg:
            return

        for phrase in phrases.split('|'):
            clear_msg = msg_parse(msg, phrase)
            if clear_msg is not None:
                # Нашли триггер в сообщении
                model_msg = ': "{}"'.format(phrase)
                self._detected_sr(clear_msg, model_name, model_msg, vad, callback)
                return
        model_msg = ': "{}"'.format(phrases)
        # Не наши триггер в сообщении - snowboy false positive
        self._detected_sr(msg, model_name, model_msg, vad)

    def _detected(self, model_name, phrase, msg, cb):
        self.own.voice_activated_callback()
        no_hello = self.cfg.gts('no_hello')
        hello = ''
        if phrase and self.own.sys_say_chance and not no_hello:
            hello = F('{} слушает', phrase)
        self.log(F('Голосовая активация по {}{}', model_name, msg), logger.INFO)
        cb(hello, *self.own.listen(hello, voice=no_hello), model_name)

    def _detected_sr(self, msg: str, model_name: str, model_msg: str or None, vad, cb=None):
        energy, rms = (vad.energy_threshold, vad.rms()) if vad is not None else (None, None)
        if not cb:
            msg = 'Activation error: \'{}\', trigger: {}{}'.format(msg, model_name, model_msg)
            msg = recognition_msg(msg, energy, rms)
            self.log(msg, logger.DEBUG)
            return
        self.log(recognition_msg(msg, energy, rms), logger.INFO)
        self.log(F('Голосовая активация по {}{}', model_name, model_msg), logger.INFO)
        cb(False, msg, rms, model_name)

    def listen(self, r=None, mic=None, vad=None):
        r = r or sr.Recognizer(self.own.record_callback, self.cfg.gt('listener', 'silent_multiplier'))
        mic = mic or sr.Microphone(device_index=self.own.mic_index)
        with mic as source:
            vad = vad or self.get_vad_detector(source)
            record_time = time.time()
            try:
                adata = self._listen(r, source, vad)
            except (sr.WaitTimeoutError, RuntimeError):
                adata = None
            record_time = time.time() - record_time
        return adata, record_time, vad.energy_threshold, vad.rms()

    def _listen(self, r, source, vad, frames=None, hw_time=None):
        def positive_or_none(val):
            return None if val < 1 else val
        phrase_time_limit = positive_or_none(self.cfg.gts('phrase_time_limit'))
        timeout = positive_or_none(self.cfg.gt('listener', 'speech_timeout'))

        if self.cfg.gt('listener', 'stream_recognition'):
            return r.listen2(source, vad, self.own.voice_recognition, timeout, phrase_time_limit, frames, hw_time)
        else:
            return r.listen1(source, vad, timeout, phrase_time_limit, frames, hw_time)

    def background_listen(self):
        def callback(interrupt_check, mic, detector):
            r = sr.Recognizer(silent_multiplier=self.cfg.gt('listener', 'silent_multiplier'))
            adata = None
            while not interrupt_check():
                with mic as source:
                    try:
                        adata = self._listen(r, source, detector)
                    except sr.WaitTimeoutError:
                        continue
                    except RuntimeError:
                        adata = None
                    break
            return adata

        mic_ = sr.Microphone(device_index=self.own.mic_index)
        return NonBlockListener(callback, mic_, self.get_vad_detector(mic_))

    def get_vad_detector(self, source_or_mic, vad_mode=None, vad_lvl=None, energy_lvl=None, energy_dynamic=None):
        detector, _ = self._get_vad_detector(source_or_mic, vad_mode, vad_lvl, energy_lvl, energy_dynamic)
        return detector

    def _get_vad_detector(self, source_or_mic, vad_mode=None, vad_lvl=None, energy_lvl=None, energy_dynamic=None):
        vad = self._select_vad(vad_mode)
        vad_lvl = vad_lvl if vad_lvl is not None else self.cfg.gt('listener', 'vad_lvl')
        vad_lvl = min(3, max(0, vad_lvl))
        energy_lvl = energy_lvl if energy_lvl is not None else self.cfg.gt('listener', 'energy_lvl')
        energy_lvl = energy_lvl if energy_lvl > 10 else 0
        energy_dynamic = energy_dynamic if energy_dynamic is not None else self.cfg.gt('listener', 'energy_dynamic')
        cfg = self._detector_cfg(
            source=source_or_mic, energy_lvl=energy_lvl, energy_dynamic=energy_dynamic, lvl=vad_lvl,
            width=source_or_mic.SAMPLE_WIDTH, rate=source_or_mic.SAMPLE_RATE, another=None,
        )
        vad = vad(**cfg)
        if isinstance(vad, sr.EnergyDetectorVAD):
            if not energy_lvl:
                manual_exit = source_or_mic.stream is None
                try:
                    if manual_exit:
                        source_or_mic.__enter__()
                    vad.adjust_for_ambient_noise(source_or_mic.stream, source_or_mic.CHUNK)
                finally:
                    if manual_exit:
                        source_or_mic.__exit__(None, None, None)
            if energy_dynamic:
                return vad, self.own.noising
        return vad, None

    def _get_hw_detector(self, width, rate, another_detector=None):
        cfg = self._detector_cfg(width=width, rate=rate, another=another_detector)
        return get_hot_word_detector(self.cfg.detector.NAME, **cfg)

    def _detector_cfg(self, **kwargs) -> dict:
        kwargs.update({
            'home': self.cfg.detector.path, 'hot_word_files': self.cfg.path['models_list'],
            'sensitivity': self.cfg.gts('sensitivity'), 'audio_gain': self.cfg.gts('audio_gain'),
            'apply_frontend': self.cfg.gt('noise_suppression', 'snowboy_apply_frontend'),
            'rms': self.cfg.gt('smarthome', 'send_rms'),
        })
        return kwargs

    def _select_vad(self, vad_mode=None):
        def is_loaded():
            return ModuleLoader().is_loaded(vad_mode)

        vad_mode = vad_mode if vad_mode is not None else self.cfg.gt('listener', 'vad_mode')
        if vad_mode == 'snowboy' and self.cfg.path['models_list'] and self.cfg.detector.NAME == 'snowboy' and\
                is_loaded():
            vad = SnowboyHWD
        elif vad_mode == 'webrtc' and is_loaded():
            vad = WebRTCVAD
        elif vad_mode == 'apm' and is_loaded():
            vad = APMVAD
        else:
            vad = sr.EnergyDetectorVAD
        self._print_loading_errors()
        return vad


class NonBlockListener(threading.Thread):
    def __init__(self, listener, mic, detector):
        super().__init__()
        self._listener = listener
        self._mic = mic
        self._detector = detector
        self.audio = None
        self.energy_threshold = None
        self.rms = None
        self._has_stop = False
        self._work = False

    def run(self):
        self.audio = self._listener(self._interrupt_check, self._mic, self._detector)
        self.energy_threshold, self.rms = self._detector.energy_threshold, self._detector.rms()
        self._has_stop = True

    def work(self):
        return not self._has_stop

    def start(self):
        self._work = True
        super().start()

    def stop(self, timeout=30):
        self._has_stop = True
        if self._work:
            self._work = False
            self.join(timeout)

    def _interrupt_check(self):
        return self._has_stop


def msg_parse(msg: str, phrase: str):
    phrase2 = phrase.lower().replace('ё', 'е')
    msg2 = msg.lower().replace('ё', 'е')
    offset = msg2.find(phrase2)
    if offset < 0:  # Ошибка активации
        return
    msg = msg[offset+len(phrase):]
    for l_del in ('.', ',', ' '):
        msg = msg.lstrip(l_del)
    return msg
