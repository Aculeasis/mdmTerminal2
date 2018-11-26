#!/usr/bin/env python3

import os

import lib.snowboydecoder as snowboydecoder
import lib.sr_proxifier as sr


class SnowBoy:
    def __init__(self, cfg, callback, interrupt_check, *_, **__):
        sensitivity = [cfg.gts('sensitivity')]
        decoder_model = cfg.path['models_list']
        self._interrupt_check = interrupt_check
        self._callbacks = [callback for _ in decoder_model]
        self._snowboy = snowboydecoder.HotwordDetector(decoder_model=decoder_model, sensitivity=sensitivity)

    def start(self):
        self._snowboy.start(detected_callback=self._callbacks, interrupt_check=self._interrupt_check)

    def terminate(self):
        self._snowboy.terminate()


class SnowBoySR:
    def __init__(self, cfg, callback, interrupt_check, stt, play):
        self._sensitivity = cfg.gts('sensitivity')
        self._decoder_model = cfg.path['models_list']
        self._callback = callback
        self._interrupt_check = interrupt_check
        self._stt = stt
        self._cfg = cfg
        self._sb_path = os.path.join(self._cfg.path['home'], 'lib')
        self._play = play
        self._hotword_callback = play.full_quiet if self._cfg.gts('chrome_choke') else None
        self._terminate = False

    def start(self):
        self._terminate = False
        while not self._interrupted():
            msg = ''
            with sr.Microphone() as source:
                r = sr.Recognizer(self._interrupted, self._sensitivity, self._hotword_callback)
                energy_threshold = self._stt.energy.correct(r, source)
                try:
                    adata = r.listen(source, 5, 10, (self._sb_path, self._decoder_model))
                except sr.WaitTimeoutError:
                    self._stt.energy.set(None)
                    continue
                except RuntimeError:
                    self._stt.energy.set(energy_threshold)
                    continue
            model = r.get_model
            if model:  # Не распознаем если модель не опознана
                msg = self._get_text(adata)
            if msg and model:
                if self._callback(msg, model, energy_threshold):
                    self._stt.energy.set(energy_threshold)
                else:
                    self._stt.energy.set(None)
                continue

    def terminate(self):
        self._terminate = True

    def _interrupted(self):
        return self._terminate or self._interrupt_check()

    def _get_text(self, adata):
        alarm = self._cfg.gts('chrome_alarmstt')
        if alarm:
            self._play.play(self._cfg.path['dong'], lvl=5)
        try:
            return self._stt.voice_recognition(adata, 2)
        finally:
            if alarm:
                self._play.clear_lvl()
