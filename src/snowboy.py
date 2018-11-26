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
        self._cfg = cfg
        self._callback = callback
        self._interrupt_check = interrupt_check
        self._stt = stt
        self._play = play
        self._hotword_callback = play.full_quiet if self._cfg.gts('chrome_choke') else None
        self._terminate = False

    def start(self):
        self._terminate = False
        while not self._interrupted():
            with sr.Microphone() as source:
                r = sr.Recognizer(self._interrupted, self._cfg.gts('sensitivity'), self._hotword_callback)
                energy_threshold = self._stt.energy.correct(r, source)
                try:
                    adata = r.listen(source, 5, self._cfg.gts('phrase_time_limit'),
                                     (self._cfg.path['home'], self._cfg.path['models_list']))
                except sr.WaitTimeoutError:
                    self._stt.energy.set(None)
                    continue
                except sr.Interrupted:
                    self._stt.energy.set(energy_threshold)
                    continue
            model = r.get_model
            if model < 1:
                continue
            self._adata_parse(adata, model, energy_threshold)

    def terminate(self):
        self._terminate = True

    def _adata_parse(self, adata, model, energy_threshold):
        model_name, phrase, model_msg = self._cfg.model_info_by_id(model)
        if not phrase:
            return
        msg = self._get_text(adata)
        if msg:
            clear_msg = self._msg_parse(msg, phrase)
            if clear_msg is None:
                self._stt.energy.set(None)
                self._callback(msg, None, None, None)
            else:
                self._stt.energy.set(energy_threshold)
                self._callback(clear_msg, model_name, model_msg, energy_threshold)

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

    @staticmethod
    def _msg_parse(msg: str, phrase: str):
        phrase2 = phrase.lower().replace('ё', 'е')
        msg2 = msg.lower().replace('ё', 'е')
        offset = msg2.find(phrase2)
        if offset < 0:  # Ошибка активации
            return
        msg = msg[offset+len(phrase):]
        for l_del in ('.', ',', ' '):
            msg = msg.lstrip(l_del)
        return msg
