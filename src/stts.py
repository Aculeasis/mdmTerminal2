#!/usr/bin/env python3

import hashlib
import os
import os.path
import random
import threading
import time
import wave

import pyaudio

import lib.STT as STT
import lib.TTS as TTS
import lib.sr_wrapper as sr
import logger
import utils
from languages import LANG_CODE
from languages import STTS as LNG


class TextToSpeech:
    def __init__(self, cfg, log):
        self.log = log
        self._cfg = cfg

    def tts(self, msg, realtime: bool = True):
        wrapper = _TTSWrapper(self._cfg, self.log, msg, realtime)
        if not self._cfg.get('optimistic_nonblock_tts', 0):
            wrapper.event.wait(600)
        return wrapper.get


class _TTSWrapper(threading.Thread):
    PROVIDERS = frozenset({'google', 'yandex', 'rhvoice-rest', 'rhvoice', 'aws'})

    def __init__(self, cfg, log, msg, realtime):
        super().__init__()
        self.cfg = cfg
        self.log = log
        self.msg = msg if isinstance(msg, str) else str(msg)
        self.realtime = realtime
        self.file_path = None
        self._stream = None
        self._ext = None
        self.event = threading.Event()
        self.work_time = None
        self._buff_size = 1024
        self.start_time = time.time()
        self.start()

    def get(self):
        self.event.wait(600)
        self._unlock()
        return self.file_path, self._stream, self._ext

    def run(self):
        wtime = time.time()
        sha1 = hashlib.sha1(self.msg.encode()).hexdigest()
        provider = self.cfg.gts('providertts', 'google')
        ext = 'mp3' if self.cfg.yandex_api(provider) != 2 else 'opus'
        find_part = ''.join(('_', sha1, '.'))
        rname = find_part + ext
        if self.realtime:
            self.log('say \'{}\''.format(self.msg), logger.INFO)
            msg_gen = ''
        else:
            msg_gen = '\'{}\' '.format(self.msg)
        use_cache = self.cfg['cache'].get('tts_size', 50) > 0

        self.file_path = self._find_in_cache(provider, find_part, ext) if use_cache else None
        if self.file_path:
            self._unlock()
            work_time = time.time() - wtime
            action = LNG['action_cache'].format(msg_gen)
            time_diff = ''
        else:
            if not use_cache and provider in ('rhvoice-rest', 'rhvoice'):
                format_ = 'wav'
                self._buff_size = 1024 * 4
            else:
                format_ = ext
            self.file_path = os.path.join(self.cfg.gt('cache', 'path'), provider + rname) if use_cache else \
                '<{}><{}>'.format(sha1, format_)
            self._tts_gen(self.file_path if use_cache else None, format_, self.msg)
            self._unlock()
            work_time = time.time() - wtime
            action = LNG['action_gen'].format(msg_gen, provider)
            reply = utils.pretty_time(self.work_time) if self.work_time is not None else 'NaN'
            diff = utils.pretty_time(work_time - self.work_time) if self.work_time is not None else 'NaN'
            time_diff = ' [reply:{}, diff:{}]'.format(reply, diff)
        self.log(
            LNG['for_time'].format(action, utils.pretty_time(work_time), time_diff, self.file_path),
            logger.DEBUG if self.realtime else logger.INFO
        )

    def _unlock(self):
        if self.work_time is None:
            self.work_time = time.time() - self.start_time
        self.event.set()

    def _find_in_cache(self, prov: str, rname: str, ext: str):
        prov_priority = self.cfg['cache'].get('tts_priority', '')
        file = None
        if prov_priority in self.PROVIDERS:  # Приоритет
            file = self._file_check(prov_priority, rname, ext)

        if not file and prov_priority != prov:  # Обычная, второй раз не чекаем
            file = self._file_check(prov, rname, ext)

        if not file and prov_priority == '*':  # Ищем всех
            for key in self.PROVIDERS:
                if key != prov:
                    file = self._file_check(key, rname, ext)
                if file:
                    break
        return file

    def _file_check(self, prov, rname, ext):
        if prov == 'yandex':
            for ext_ in ('mp3', 'opus'):
                file = os.path.join(self.cfg.gt('cache', 'path'), prov + rname + ext_)
                if os.path.isfile(file):
                    return file
            return ''
        file = os.path.join(self.cfg.gt('cache', 'path'), prov + rname + ext)
        return file if os.path.isfile(file) else ''

    def _tts_gen(self, file, format_, msg: str):
        prov = self.cfg.gts('providertts', 'unset')
        key = None
        if TTS.support(prov):
            sets = utils.rhvoice_rest_sets(self.cfg[prov]) if prov == 'rhvoice-rest' else {}
            try:
                key = self.cfg.key(prov, 'apikeytts')
                lang = LANG_CODE['ISO'] if prov == 'google' else LANG_CODE['IETF']
                tts = TTS.GetTTS(
                    prov,
                    text=msg,
                    buff_size=self._buff_size,
                    speaker=self.cfg.gt(prov, 'speaker'),
                    audio_format=format_,
                    key=key,
                    lang=lang,
                    emotion=self.cfg.gt(prov, 'emotion'),
                    url=self.cfg.gt(prov, 'server'),
                    sets=sets,
                    yandex_api=self.cfg.yandex_api(prov)
                )
            except(RuntimeError, TTS.gTTSError, ValueError) as e:
                self._synthesis_error(prov, key, e)
                self.file_path = self.cfg.path['tts_error']
                return
        else:
            self.log(LNG['unknown_prov'].format(prov), logger.CRIT)
            self.file_path = self.cfg.path['tts_error']
            return
        self._stream = utils.FakeFP()
        write_to = [self._stream]
        if file:
            write_to.append(open(file, 'wb'))
        self._ext = '.{}'.format(format_) if not file else None
        self._unlock()
        try:
            tts.stream_to_fps(write_to)
        except (RuntimeError, TTS.gTTSError, ValueError) as e:
            self._synthesis_error(prov, key, e)
        for fp in write_to:
            fp.close()
        return

    def _synthesis_error(self, prov, key, e):
        self.log(LNG['err_synthesis'].format(prov, key, e), logger.CRIT)


class SpeechToText:
    def __init__(self, cfg, play_, log, tts, record_callback):
        self.log = log
        self._cfg = cfg
        self.sys_say = Phrases(log, cfg)
        self._lock = threading.Lock()
        self._work = True
        self._play = play_
        self._tts = tts
        self._record_callback = record_callback
        self.energy = utils.EnergyControl(cfg, play_)
        self._recognizer = sr.Recognizer()
        try:
            self.max_mic_index = len(sr.Microphone().list_microphone_names()) - 1
        except OSError as e:
            self.log('Error get list microphones: {}'.format(e), logger.CRIT)
            self.max_mic_index = -2

    def reload(self):
        self.sys_say = Phrases(self.log, self._cfg)

    def start(self):
        self._work = True
        self.log('start.', logger.INFO)

    def stop(self):
        self._work = False
        self.log('stop.', logger.INFO)

    def busy(self):
        return self._lock.locked() and self._work

    def listen(self, hello: str = '', deaf: bool = True, voice: bool = False) -> str:
        if not self._work:
            return ''
        if self.max_mic_index != -2:
            self._lock.acquire()
            try:
                msg = self._listen_and_take(hello, deaf, voice)
            finally:
                self._lock.release()
        else:
            self.log(LNG['no_mics'], logger.ERROR)
            msg = LNG['no_mics']
        return msg

    def _listen_and_take(self, hello, deaf, voice) -> str:
        ask_me_again = self._cfg.get_uint('ask_me_again')
        msg = self._listen(hello, voice)

        while msg is None and ask_me_again:  # Переспрашиваем
            ask_me_again -= 1
            msg = self._listen(self.sys_say.ask, False)
        if msg is None and deaf:
            say = self.sys_say.deaf
            if say:
                self._play.say(say, blocking=120 if self._cfg.gts('blocking_listener') else 0)
        return msg or ''

    def get_mic_index(self):
        device_index = self._cfg.gts('mic_index', -1)
        if device_index > self.max_mic_index:
            if self.max_mic_index >= 0:
                mics = LNG['mics_to'].format(self.max_mic_index + 1, self.max_mic_index)
            else:
                mics = LNG['no_mics']
            self.log(LNG['wrong_mic_index'].format(device_index, mics), logger.WARN)
            return None
        return None if device_index < 0 else device_index

    def _listen(self, hello: str, voice) -> str or None:
        lvl = 5  # Включаем монопольный режим
        commands = None

        if self._cfg.gts('alarmkwactivated'):
            self._play.play(self._cfg.path['ding'], lvl, wait=0.01, blocking=2)
        else:
            self._play.set_lvl(lvl)
            self._play.kill_popen()
        self.log('audio devices: {}'.format(pyaudio.PyAudio().get_device_count() - 1), logger.DEBUG)

        hello = hello or self.sys_say.hello
        file_path = self._tts(hello) if not voice and hello else None

        if self._cfg.gts('blocking_listener'):
            audio, record_time, energy_threshold = self._block_listen(hello, lvl, file_path)
        else:
            audio, record_time, energy_threshold = self._non_block_listen(hello, lvl, file_path)

        self.log(LNG['record_for'].format(utils.pretty_time(record_time)), logger.INFO)
        # Выключаем монопольный режим
        self._play.clear_lvl()

        if self._cfg.gts('alarmstt'):
            self._play.play(self._cfg.path['dong'])
        if audio is not None:
            commands = self.voice_recognition(audio)

        if commands:
            msg = ''
            if energy_threshold:
                self.energy.set(energy_threshold)
                msg = ', energy_threshold={}'.format(int(energy_threshold))
            self.log(LNG['recognized'].format(commands, msg), logger.INFO)
        else:
            self.energy.set(None)
        return commands

    def _non_block_listen(self, hello, lvl, file_path):
        max_play_time = 120  # максимальное время воспроизведения приветствия
        max_wait_time = 10  # ожидание после приветствия

        r = sr.Recognizer()
        mic = sr.Microphone(device_index=self.get_mic_index())

        with mic as source:  # Слушаем шум 1 секунду, потом распознаем, если раздажает задержка можно закомментировать.
            energy_threshold = self.energy.correct(r, source)

        if self._cfg.gts('alarmtts') and not hello:
            self._play.play(self._cfg.path['dong'], lvl)

        start_wait = time.time()
        if file_path:
            self._play.play(file_path, lvl)

        # Начинаем фоновое распознавание голосом после того как запустился плей.
        listener = NonBlockListener(r=r, source=mic, phrase_time_limit=self._cfg.gts('phrase_time_limit', 15))
        self._record_callback(True)
        if file_path:
            while listener.work() and self._play.really_busy() and \
                    time.time() - start_wait < max_play_time and self._work:
                # Ждем пока время не выйдет, голос не распознался и файл играет
                time.sleep(0.01)
        self._play.quiet()

        start_wait2 = time.time()
        while listener.work() and time.time() - start_wait2 < max_wait_time and self._work:
            # ждем еще секунд 10
            time.sleep(0.01)

        record_time = time.time() - start_wait
        listener.stop()
        self._record_callback(False)
        return listener.audio, record_time, energy_threshold

    def _block_listen(self, hello, lvl, file_path, self_call=False):
        with sr.Microphone(device_index=self.get_mic_index()) as source:
            r = sr.Recognizer()
            r.set_record_callback(self._record_callback)
            if self._cfg.gts('alarmtts') and not hello:
                self._play.play(self._cfg.path['dong'], lvl, wait=0.01, blocking=2)

            if file_path:
                self._play.play(file_path, lvl, wait=0.01, blocking=120)
            energy_threshold = self.energy.correct(r, source)

            record_time = time.time()
            try:
                audio = r.listen(source, timeout=10, phrase_time_limit=self._cfg.gts('phrase_time_limit', 15))
            except sr.WaitTimeoutError:
                audio = None
            record_time = time.time() - record_time
        if record_time < 0.5 and not self_call:
            # Если от инициализации микрофона до записи прошло больше 20-35 сек, то запись ломается
            # Игнорируем полученную запись и запускаем новую, без приветствий
            self.log('Long ask fix!', logger.DEBUG)
            return self._block_listen(hello=True, lvl=lvl, file_path=None, self_call=True)
        else:
            return audio, record_time, energy_threshold

    def voice_record(self, hello: str, save_to: str, convert_rate=None, convert_width=None):
        if self.max_mic_index == -2:
            self.log(LNG['no_mics'], logger.ERROR)
            return LNG['no_mics']
        self._lock.acquire()
        try:
            return self._voice_record(hello, save_to, convert_rate, convert_width)
        finally:
            self._play.clear_lvl()
            self._lock.release()

    def _voice_record(self, hello: str, save_to: str, convert_rate=None, convert_width=None):
        lvl = 5  # Включаем монопольный режим

        file_path = self._tts(hello)()
        self._play.say(file_path, lvl, True, is_file=True, blocking=120)
        with sr.Microphone(device_index=self.get_mic_index()) as source:
            r = sr.Recognizer()
            r.adjust_for_ambient_noise(source)
            self._play.play(self._cfg.path['ding'], lvl, blocking=3)

            record_time = time.time()
            try:
                adata = r.listen(source=source, timeout=5, phrase_time_limit=10)
            except sr.WaitTimeoutError as e:
                return str(e)
            if time.time() - record_time < 0.5:
                return LNG['err_voice_record']
        try:
            with open(save_to, "wb") as f:
                f.write(adata.get_wav_data(convert_rate, convert_width))
        except IOError as err:
            return str(err)
        else:
            return None

    def voice_recognition(self, audio, quiet: int =0) -> str or None:
        prov = self._cfg.gts('providerstt', 'google')
        if quiet < 2:
            self.log(LNG['recognized_from'].format(prov), logger.DEBUG)
        wtime = time.time()
        try:
            key = self._cfg.key(prov, 'apikeystt')
            lang = LANG_CODE['IETF']
            if prov == 'google':
                command = STT.Google(audio, lang=lang).text()
            elif prov == 'wit.ai':
                command = self._recognizer.recognize_wit(audio, key=key)
            elif prov == 'microsoft':
                command = self._recognizer.recognize_bing(audio, key=key, language=lang)
            elif prov == 'pocketsphinx-rest':
                command = STT.PocketSphinxREST(
                    audio_data=audio,
                    url=self._cfg.gt(prov, 'server', 'http://127.0.0.1:8085')
                ).text()
            elif prov == 'yandex':
                if self._cfg.yandex_api(prov) == 2:
                    command = STT.YandexCloud(audio_data=audio, key=key, lang=lang).text()
                else:
                    command = STT.Yandex(audio_data=audio, key=key, lang=lang).text()
            else:
                self.log(LNG['err_unknown_prov'].format(prov), logger.CRIT)
                return ''
        except (sr.UnknownValueError, STT.UnknownValueError):
            return ''
        except (sr.RequestError, RuntimeError) as e:
            if not quiet:
                self._play.say(LNG['err_stt_say'])
            self.log(LNG['err_stt_log'].format(e), logger.ERROR)
            return ''
        else:
            if quiet >= 2:
                self.log(LNG['recognized_from'].format(prov), logger.DEBUG)
            self.log(LNG['recognized_for'].format(utils.pretty_time(time.time() - wtime)), logger.DEBUG)
            return command or ''

    def phrase_from_files(self, files: list):
        if not files:
            return ''
        workers = [RecognitionWorker(self.voice_recognition, file) for file in files]
        result = [worker.get for worker in workers]
        del workers
        # Фраза с 50% + 1 побеждает
        consensus = len(result) // 2 + 1
        phrase = ''
        match_count = 0
        for say in result:
            match_count = result.count(say)
            if match_count >= consensus:
                phrase = say
                break
        self.log(LNG['consensus'].format(', '.join([str(x) for x in result]), phrase), logger.DEBUG)
        return phrase, match_count


class RecognitionWorker(threading.Thread):
    def __init__(self, voice_recognition, file_path):
        super().__init__()
        self._voice_recognition = voice_recognition
        self._file_path = file_path
        self._result = ''
        self.start()

    def run(self):
        with wave.open(self._file_path, 'rb') as fp:
            adata = sr.AudioData(fp.readframes(fp.getnframes()), fp.getframerate(), fp.getsampwidth())
        self._result = self._voice_recognition(adata, 1)

    @property
    def get(self):
        super().join()
        return self._result


class NonBlockListener:
    def __init__(self, r, source, phrase_time_limit):
        self.audio = None
        self.stop = r.listen_in_background(source, self._callback, phrase_time_limit=phrase_time_limit)

    def work(self):
        return self.audio is None

    def _callback(self, _, audio):
        if self.work():
            self.audio = audio


class Phrases:
    def __init__(self, log, cfg):
        name = 'phrases_{}'.format(LANG_CODE['ISO'])
        self._phrases = cfg.load_dict(name)
        try:
            utils.check_phrases(self._phrases)
        except ValueError as e:
            log('Error phrases loading, restore default phrases: {}'.format(e), logger.ERROR)
            self._phrases = None
        if not self._phrases:
            self._phrases = {'hello': LNG['p_hello'], 'deaf': LNG['p_deaf'], 'ask': LNG['p_ask'], 'chance': 25}
            cfg.save_dict(name, self._phrases, True)

    @property
    def hello(self) -> str:
        return random.SystemRandom().choice(self._phrases['hello'])

    @property
    def deaf(self) -> str:
        return random.SystemRandom().choice(self._phrases['deaf'])

    @property
    def ask(self) -> str:
        return random.SystemRandom().choice(self._phrases['ask'])

    @property
    def chance(self) -> bool:
        return random.SystemRandom().randint(1, 100) <= self._phrases['chance']
