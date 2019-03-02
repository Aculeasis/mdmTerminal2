#!/usr/bin/env python3

import threading
import time

import lib.snowboydecoder as snowboydecoder
from lib import sr_wrapper as sr
from lib.audio_utils import APM_ERR, Vad
from lib.audio_utils import SnowboyDetector, DetectorVAD, DetectorAPM
from owner import Owner


class Listener:
    def __init__(self, cfg, owner: Owner, *_, **__):
        self.cfg = cfg
        self.own = owner

    def listen(self, r=None, mic=None, detector=None, timeout=10):
        r = r or sr.Recognizer(self.own.record_callback, self.cfg.gt('listener', 'silent_multiplier'))
        mic = mic or sr.Microphone(device_index=self.own.mic_index)
        with mic as source:
            detector = detector or self.get_detector(source)
            record_time = time.time()
            try:
                adata = self._listen(r, source, detector, timeout=timeout)
            except (sr.WaitTimeoutError, RuntimeError):
                adata = None
            record_time = time.time() - record_time
        return adata, record_time, detector.energy_threshold if isinstance(detector, sr.EnergyDetector) else None

    def background_listen(self):
        mic = sr.Microphone(device_index=self.own.mic_index)
        return NonBlockListener(self._background_listen, mic, self.get_detector(mic))

    def chrome_listen(self, interrupt_check, callback):
        r = sr.Recognizer(self.own.record_callback, self.cfg.gt('listener', 'silent_multiplier'))
        while not interrupt_check():
            with sr.Microphone(device_index=self.own.mic_index) as source:
                detector, noising = self._get_detector(source, self.cfg.gt('listener', 'vad_chrome') or None)
                if not isinstance(detector, SnowboyDetector):
                    sn = self._get_snowboy(source.SAMPLE_WIDTH, source.SAMPLE_RATE, detector)
                else:
                    sn = detector
                try:
                    snowboy_result, frames, elapsed_time = r.snowboy_wait(source, sn, interrupt_check, noising)
                except sr.Interrupted:
                    continue
                except RuntimeError:
                    return
                model_name, phrase, _ = self.cfg.model_info_by_id(snowboy_result)
                if not phrase:
                    continue
                if self.cfg.gts('chrome_choke'):
                    self.own.full_quiet()
                try:
                    adata = self._listen(r, source, detector, 3, frames=frames, sn_time=elapsed_time)
                except (sr.WaitTimeoutError, RuntimeError):
                    continue
            energy_threshold = detector.energy_threshold if isinstance(detector, sr.EnergyDetector) else None
            self._adata_parse(adata, model_name, phrase, energy_threshold, callback)

    def get_detector(self, source_or_mic, vad_mode=None, vad_lvl=None, energy_lvl=None, energy_dynamic=None):
        detector, _ = self._get_detector(source_or_mic, vad_mode, vad_lvl, energy_lvl, energy_dynamic)
        return detector

    def _listen(self, r, source, detector, timeout, phrase_time_limit=None, frames=None, sn_time=None):
        if phrase_time_limit is None:
            phrase_time_limit = self.cfg.gts('phrase_time_limit')
        if self.cfg.gt('listener', 'stream_recognition'):
            return r.listen2(source, detector, self.own.voice_recognition, timeout, phrase_time_limit, frames, sn_time)
        else:
            return r.listen1(source, detector, timeout, phrase_time_limit, frames, sn_time)

    def _background_listen(self, interrupt_check, mic, detector):
        r = sr.Recognizer(silent_multiplier=self.cfg.gt('listener', 'silent_multiplier'))
        adata = None
        while not interrupt_check():
            with mic as source:
                try:
                    adata = self._listen(r, source, detector, timeout=1)
                except sr.WaitTimeoutError:
                    continue
                except RuntimeError:
                    adata = None
                break
        return adata, detector.energy_threshold if isinstance(detector, sr.EnergyDetector) else None

    def _adata_parse(self, adata, model_name: str, phrases: str, energy_threshold, callback):
        msg = self._get_text(adata)
        if not msg:
            return

        for phrase in phrases.split('|'):
            clear_msg = msg_parse(msg, phrase)
            if clear_msg is not None:
                # Нашли триггер в сообщении
                model_msg = ': "{}"'.format(phrase)
                callback(clear_msg, model_name, model_msg, energy_threshold)
                return
        # Не наши триггер в сообщении - snowboy false positive
        callback(msg, phrases, None, energy_threshold)

    def _get_text(self, adata):
        if self.cfg.gts('chrome_alarmstt'):
            self.own.play(self.cfg.path['dong'])
        return self.own.voice_recognition(adata)

    def _get_detector(self, source_or_mic, vad_mode=None, vad_lvl=None, energy_lvl=None, energy_dynamic=None):
        vad = self._select_vad(vad_mode)
        vad_lvl = vad_lvl if vad_lvl is not None else self.cfg.gt('listener', 'vad_lvl')
        vad_lvl = min(3, max(0, vad_lvl))
        energy_lvl = energy_lvl if energy_lvl is not None else self.cfg.gt('listener', 'energy_lvl')
        energy_lvl = energy_lvl if energy_lvl > 10 else 0
        energy_dynamic = energy_dynamic if energy_dynamic is not None else self.cfg.gt('listener', 'energy_dynamic')
        vad = vad(
            source=source_or_mic, energy_lvl=energy_lvl, energy_dynamic=energy_dynamic,
            lvl=vad_lvl, width=source_or_mic.SAMPLE_WIDTH, rate=source_or_mic.SAMPLE_RATE,
            resource_path=self.cfg.path['home'], snowboy_hot_word_files=self.cfg.path['models_list'],
            sensitivity=self.cfg.gts('sensitivity'), audio_gain=self.cfg.gts('audio_gain'), another=None,
            apply_frontend=self.cfg.gt('noise_suppression', 'snowboy_apply_frontend')
        )
        if isinstance(vad, sr.EnergyDetector):
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

    def _get_snowboy(self, width, rate, another_detector=None):
        return SnowboyDetector(
            resource_path=self.cfg.path['home'], snowboy_hot_word_files=self.cfg.path['models_list'],
            width=width, rate=rate,
            sensitivity=self.cfg.gts('sensitivity'), audio_gain=self.cfg.gts('audio_gain'), another=another_detector,
            apply_frontend=self.cfg.gt('noise_suppression', 'snowboy_apply_frontend')
        )

    def _select_vad(self, vad_mode=None):
        vad_mode = vad_mode if vad_mode is not None else self.cfg.gt('listener', 'vad_mode')
        if vad_mode == 'snowboy' and len(self.cfg.path['models_list']):
            return SnowboyDetector
        if vad_mode == 'webrtc' and Vad:
            return DetectorVAD
        if vad_mode == 'apm' and not APM_ERR:
            return DetectorAPM
        return sr.EnergyDetector


class SnowBoy:
    def __init__(self, cfg, callback, interrupt_check, owner: Owner):
        sensitivity = [cfg.gts('sensitivity')]
        decoder_model = cfg.path['models_list']
        audio_gain = cfg.gts('audio_gain')
        self._interrupt_check = interrupt_check
        self._callbacks = [callback for _ in decoder_model]
        self._snowboy = snowboydecoder.HotwordDetector(
            decoder_model=decoder_model,
            sensitivity=sensitivity,
            audio_gain=audio_gain,
            device_index=owner.mic_index
        )
        self._snowboy.detector.ApplyFrontend(cfg.gt('noise_suppression', 'snowboy_apply_frontend'))

    def start(self):
        self._snowboy.start(detected_callback=self._callbacks, interrupt_check=self._interrupt_check)

    def terminate(self):
        self._snowboy.terminate()


class SnowBoySR:
    def __init__(self, _, callback, interrupt_check, owner: Owner):
        self._callback = callback
        self._interrupt_check = interrupt_check
        self.own = owner
        self._terminate = False

    def start(self):
        self._terminate = False
        self.own.chrome_listen(self._interrupted, self._callback)

    def terminate(self):
        self._terminate = True

    def _interrupted(self):
        return self._terminate or self._interrupt_check()


class NonBlockListener(threading.Thread):
    def __init__(self, listener, mic, detector):
        super().__init__()
        self._listener = listener
        self._mic = mic
        self._detector = detector
        self.audio = None
        self.energy_threshold = None
        self._has_stop = False
        self._work = False

    def run(self):
        self.audio, self.energy_threshold = self._listener(self._interrupt_check, self._mic, self._detector)
        self._has_stop = True

    def work(self):
        return not self._has_stop

    def start(self):
        self._work = True
        super().start()

    def stop(self):
        self._has_stop = True
        if self._work:
            self._work = False
            self.join(30)

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
