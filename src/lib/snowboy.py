import lib.snowboydecoder as snowboydecoder
import lib.sr_wrapper as sr
from owner import Owner


class SnowBoy:
    def __init__(self, cfg, callback, interrupt_check, *_, **__):
        sensitivity = [cfg.gts('sensitivity')]
        decoder_model = cfg.path['models_list']
        audio_gain = cfg.gts('audio_gain')
        self._interrupt_check = interrupt_check
        self._callbacks = [callback for _ in decoder_model]
        self._snowboy = snowboydecoder.HotwordDetector(
            decoder_model=decoder_model,
            sensitivity=sensitivity,
            audio_gain=audio_gain
        )

    def start(self):
        self._snowboy.start(detected_callback=self._callbacks, interrupt_check=self._interrupt_check)

    def terminate(self):
        self._snowboy.terminate()


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


class SnowBoySR:
    def __init__(self, cfg, callback, interrupt_check, owner: Owner):
        self._cfg = cfg
        self._callback = callback
        self._interrupt_check = interrupt_check
        self.own = owner
        self._hotword_callback = owner.full_quiet if self._cfg.gts('chrome_choke') else None
        self._terminate = False

    def start(self):
        self._terminate = False
        while not self._interrupted():
            with sr.Microphone() as source:
                r = sr.Recognizer(
                    self._interrupted, self._cfg.gts('sensitivity'), self._hotword_callback, self._cfg.gts('audio_gain')
                )
                r.set_record_callback(self.own.record_callback)
                energy_threshold = self.own.energy_correct(r, source)
                try:
                    adata = r.listen(source, 5, self._cfg.gts('phrase_time_limit'),
                                     (self._cfg.path['home'], self._cfg.path['models_list']))
                except sr.WaitTimeoutError:
                    self.own.energy_set(None)
                    continue
                except sr.Interrupted:
                    self.own.energy_set(energy_threshold)
                    continue
            if r.get_model > 0:
                self._adata_parse(adata, r.get_model, energy_threshold)

    def terminate(self):
        self._terminate = True

    def _adata_parse(self, adata, model, energy_threshold):
        model_name, phrase, model_msg = self._cfg.model_info_by_id(model)
        if not phrase:
            return
        msg = self._get_text(adata)
        if msg:
            clear_msg = msg_parse(msg, phrase)
            if clear_msg is None:
                self.own.energy_set(None)
                self._callback(msg, phrase, None, energy_threshold)
            else:
                self.own.energy_set(energy_threshold)
                self._callback(clear_msg, model_name, model_msg, energy_threshold)

    def _interrupted(self):
        return self._terminate or self._interrupt_check()

    def _get_text(self, adata):
        alarm = self._cfg.gts('chrome_alarmstt')
        if alarm:
            self.own.play(self._cfg.path['dong'], lvl=5)
        try:
            return self.own.voice_recognition(adata, True)
        finally:
            if alarm:
                self.own.clear_lvl()


class SnowBoySR2(SnowBoySR):
    def start(self):
        self._terminate = False
        r = sr.Recognizer(
            self._interrupted, self._cfg.gts('sensitivity'), self._hotword_callback, self._cfg.gts('audio_gain')
        )
        r.adaptive_noising(self.own.noising)
        r.set_record_callback(self.own.record_callback)
        while not self._interrupted():
            with sr.Microphone() as source:
                try:
                    adata = r.listen(source, 5, self._cfg.gts('phrase_time_limit'),
                                     (self._cfg.path['home'], self._cfg.path['models_list']))
                except (sr.WaitTimeoutError, sr.Interrupted):
                    continue
            if r.get_model > 0:
                self._adata_parse(adata, r.get_model, r.energy_threshold)

    def _adata_parse(self, adata, model, energy_threshold):
        model_name, phrase, model_msg = self._cfg.model_info_by_id(model)
        if not phrase:
            return
        msg = self._get_text(adata)
        if msg:
            clear_msg = msg_parse(msg, phrase)
            if clear_msg is None:
                self._callback(msg, phrase, None, energy_threshold)
            else:
                self._callback(clear_msg, model_name, model_msg, energy_threshold)


class SnowBoySR3(SnowBoySR2):
    def start(self):
        self._terminate = False
        r = sr.Recognizer(
            self._interrupted, self._cfg.gts('sensitivity'), self._hotword_callback, self._cfg.gts('audio_gain')
        )
        r.no_energy_threshold()
        r.set_record_callback(self.own.record_callback)
        while not self._interrupted():
            with sr.Microphone() as source:
                try:
                    adata = r.listen(source, 5, self._cfg.gts('phrase_time_limit'),
                                     (self._cfg.path['home'], self._cfg.path['models_list']))
                except (sr.WaitTimeoutError, sr.Interrupted):
                    continue
            if r.get_model > 0:
                self._adata_parse(adata, r.get_model, None)
