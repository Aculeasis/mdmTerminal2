#!/usr/bin/env python3

import threading
import time

import logger
from languages import F
from lib import sr_wrapper as sr
from lib.audio_utils import ModuleLoader, SnowboyHWD, WebRTCVAD, APMVAD, StreamDetector
from owner import Owner
from utils import recognition_msg, pretty_time


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
        elif self.cfg.models and self.own.max_mic_index != -2:
            if not self.cfg.detector.MUST_PRELOAD or ModuleLoader().is_loaded(self.cfg.detector.NAME):
                return lambda: self._smart_listen(interrupt_check, callback)
            else:
                self._print_loading_errors()
        return None

    def _smart_listen(self, interrupt_check, callback):
        r = sr.Recognizer(self.own.record_callback, self.cfg.gt('listener', 'silent_multiplier'))
        adata, vad_hwd = None, None
        stream_hwd = issubclass(self.cfg.detector.DETECTOR, StreamDetector)
        chrome_mode = self.cfg.gts('chrome_mode')
        vad_name = self.cfg.gt('listener', 'vad_chrome') if chrome_mode else None
        vad_name = vad_name or self.cfg.gt('listener', 'vad_mode', '')
        while not interrupt_check():
            try:
                with sr.Microphone(device_index=self.own.mic_index) as source:
                    __vad, noising = self._get_vad_detector(source, vad_name)
                    if not isinstance(__vad, SnowboyHWD):
                        vad_hwd = self._get_hw_detector(source.SAMPLE_WIDTH, source.SAMPLE_RATE, __vad)
                    else:
                        vad_hwd = __vad
                    del __vad

                    try:
                        model_id, frames, elapsed_time = sr.wait_detection(source, vad_hwd, interrupt_check, noising)
                    except sr.Interrupted:
                        continue
                    except RuntimeError:
                        return
                    if stream_hwd:
                        model_name, phrase, msg = vad_hwd.model_info
                    else:
                        model_name, phrase, msg = self.cfg.models.model_info_by_id(model_id)
                    if chrome_mode:
                        if not phrase:
                            # модель без триггера?
                            self._detected_sr(msg or 'unset trigger', model_name, None, None)
                            continue
                        if self.cfg.gts('chrome_choke'):
                            self.own.full_quiet()
                        if stream_hwd:
                            msg_ = 'In stream voice activation {}: {}, HWD: {}'
                            self.log(msg_.format(model_name, phrase, self.cfg.detector.NAME))
                        try:
                            adata = self._listen(r, source, vad_hwd, frames, elapsed_time)
                        except (sr.WaitTimeoutError, RuntimeError):
                            continue
                if chrome_mode:
                    self._adata_parse(adata, model_name, phrase, vad_hwd, callback)
                else:
                    vad_hwd.reset()
                    self._detected(model_name, phrase, msg, callback)
            finally:
                vad_hwd and vad_hwd.die()

    def _adata_parse(self, adata, model_name: str, phrases: str, vad, callback):
        if self.cfg.gts('chrome_alarmstt'):
            self.own.play(self.cfg.path['dong'])
        msg = self.own.voice_recognition(adata)
        if not msg:
            return
        if isinstance(vad, StreamDetector):
            model_name, phrase, _ = vad.model_info
            clear_msg = msg if model_name and phrase else None
            t_ = vad.recognition_time
            msg_ = F('Распознано за {}', pretty_time(t_)) if t_ else F('Записано за {}', pretty_time(vad.record_time))
            self.log(msg_, logger.DEBUG)
        else:
            phrase, clear_msg = self.cfg.models.msg_parse(msg, phrases)

        if clear_msg is not None:
            # Нашли триггер в сообщении
            return self._detected_sr(clear_msg, model_name, ': "{}"'.format(phrase), vad, callback)
        # Не нашли триггер в сообщении - snowboy false positive
        self._detected_sr(msg, model_name, ': "{}"'.format(phrases), vad)

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
        self._recognition_sr_action(msg, energy, rms, model_name, model_msg, cb)

    def _recognition_sr_action(self, msg, energy, rms, model_name, model_msg, cb):
        self.log(recognition_msg(msg, energy, rms), logger.INFO)
        self.log(F('Голосовая активация по {}{}', model_name, model_msg), logger.INFO)
        cb(False, msg, rms, model_name)

    def detected_fake(self, text: str, rms=None, model=None, cb=None):
        rms = tuple(rms) if isinstance(rms, (list, tuple)) and len(rms) == 3 else None
        cb = cb or (lambda *_: False)
        model_msg = self.cfg.gt('models', model, '').split('|')[0] if model else ''
        model_msg = '' if not model_msg else ': "{}"'.format(model_msg)
        self._recognition_sr_action(text, None, rms, model, model_msg, cb)

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
        if isinstance(vad, StreamDetector):
            return r.listen3(source, vad, phrase_time_limit)
        elif self.cfg.gt('listener', 'stream_recognition'):
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
            vad.force_adjust_for_ambient_noise(source_or_mic)
            if energy_dynamic:
                return vad, self.own.noising
        if isinstance(vad, SnowboyHWD) and vad.revert:
            self.log('Using dirty hack for universal models, may incorrect work: {}'.format(vad.revert), logger.WARN)
            vad.revert = None
        return vad, None

    def _get_hw_detector(self, width, rate, another_detector=None):
        cfg = self._detector_cfg(width=width, rate=rate, another=another_detector, full_cfg=self.cfg)
        if self.cfg.detector.DETECTOR:
            return self.cfg.detector.DETECTOR(**cfg)
        return SnowboyHWD(**cfg)

    def _detector_cfg(self, **kwargs) -> dict:
        sensitivity = self.cfg.gts('sensitivity')
        kwargs.update({
            'home': self.cfg.detector.path, 'hot_word_files': self.cfg.models,
            'sensitivities': self.cfg.models.sensitivities(sensitivity), 'sensitivity': sensitivity,
            'audio_gain': self.cfg.gts('audio_gain'),
            'apply_frontend': self.cfg.gt('noise_suppression', 'snowboy_apply_frontend'),
            'rms': self.cfg.gt('smarthome', 'send_rms'),
        })
        return kwargs

    def _select_vad(self, vad_mode=None):
        def is_loaded():
            return ModuleLoader().is_loaded(vad_mode)

        vad_mode = vad_mode or self.cfg.gt('listener', 'vad_mode')
        if vad_mode == self.cfg.detector.NAME == 'snowboy' and self.cfg.models and is_loaded():
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
