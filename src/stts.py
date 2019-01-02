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
from lib.audio_utils import StreamRecognition
import logger
import utils
from languages import LANG_CODE
from languages import STTS as LNG
from owner import Owner


class TextToSpeech:
    def __init__(self, cfg, log):
        self._log = log
        self._cfg = cfg

    def tts(self, msg, realtime: bool = True):
        return _TTSWorker(self._cfg, self._log, msg, realtime).get


class _TTSWorker(threading.Thread):
    WAIT = 600

    def __init__(self, cfg, log, msg, realtime):
        super().__init__(name='TTSWorker')
        self.cfg = cfg
        self.log = log
        self._msg = msg if isinstance(msg, str) else str(msg)
        self._realtime = realtime
        self._event = threading.Event()
        self._buff_size = 1024

        self._file_path, self._stream, self._ext = None, None, None

        self._work_time = None
        self._start_time = time.time()
        self.start()

        if not self.cfg.get('optimistic_nonblock_tts'):
            self._wait()

    def get(self):
        self._wait()
        self._unlock()
        return self._file_path, self._stream, self._ext

    def run(self):
        provider = self.cfg.gts('providertts')
        if not TTS.support(provider):
            self.log(LNG['unknown_prov'].format(provider), logger.CRIT)
            self._file_path = self.cfg.path['tts_error']
            return self._unlock()
        msg = LNG['for_time'].format(*self._generating(provider), self._file_path)
        self.log(msg, logger.DEBUG if self._realtime else logger.INFO)

    def _generating(self, provider):
        sha1 = hashlib.sha1(self._msg.encode()).hexdigest()
        ext = 'mp3' if self.cfg.yandex_api(provider) != 2 else 'opus'
        find_part = ''.join(('_', sha1, '.'))
        rname = find_part + ext
        use_cache = self.cfg.gt('cache', 'tts_size', 50) > 0
        msg_gen = '\'{}\' '.format(self._msg)

        if self._realtime:
            self.log('say {}'.format(msg_gen), logger.INFO)
            msg_gen = ''

        if use_cache and self._found_in_cache(provider, find_part, ext):
            self._unlock()
            work_time = time.time() - self._start_time
            action = LNG['action_cache'].format(msg_gen)
            time_diff = ''
        else:
            if not use_cache and provider in ('rhvoice-rest', 'rhvoice'):
                ext = 'wav'
                self._buff_size *= 4
            self._file_path = os.path.join(self.cfg.gt('cache', 'path'), provider + rname) if use_cache else \
                '<{}><{}>'.format(sha1, ext)
            self._tts_gen(provider, self._file_path if use_cache else None, ext, self._msg)
            self._unlock()
            work_time = time.time() - self._start_time
            action = LNG['action_gen'].format(msg_gen, provider)
            reply = utils.pretty_time(self._work_time)
            diff = utils.pretty_time(work_time - self._work_time)
            time_diff = ' [reply:{}, diff:{}]'.format(reply, diff)
        return action, utils.pretty_time(work_time), time_diff

    def _unlock(self):
        if self._work_time is None:
            self._work_time = time.time() - self._start_time
        self._event.set()

    def _wait(self):
        self._event.wait(self.WAIT)

    def _found_in_cache(self, prov: str, rname: str, ext: str):
        prov_priority = self.cfg.gt('cache', 'tts_priority', '')
        self._file_path = None
        if TTS.support(prov_priority):  # Приоритет
            self._file_path = self._file_check(prov_priority, rname, ext)

        if not self._file_path and prov_priority != prov:  # Обычная, второй раз не чекаем
            self._file_path = self._file_check(prov, rname, ext)

        if not self._file_path and prov_priority == '*':  # Ищем всех
            for key in TTS.PROVIDERS:
                if key != prov:
                    self._file_path = self._file_check(key, rname, ext)
                if self._file_path:
                    break
        return self._file_path

    def _file_check(self, prov, rname, ext):
        if prov == 'yandex':
            for ext_ in ('mp3', 'opus'):
                file = os.path.join(self.cfg.gt('cache', 'path'), prov + rname + ext_)
                if os.path.isfile(file):
                    return file
            return None
        file = os.path.join(self.cfg.gt('cache', 'path'), prov + rname + ext)
        return file if os.path.isfile(file) else None

    def _tts_gen(self, provider, file, format_, msg: str):
        key = None
        sets = utils.rhvoice_rest_sets(self.cfg[provider]) if provider == 'rhvoice-rest' else {}
        try:
            key = self.cfg.key(provider, 'apikeytts')
            tts = TTS.GetTTS(
                provider,
                text=msg,
                buff_size=self._buff_size,
                speaker=self.cfg.gt(provider, 'speaker'),
                audio_format=format_,
                key=key,
                lang=self.cfg.tts_lang(provider),
                emotion=self.cfg.gt(provider, 'emotion'),
                url=self.cfg.gt(provider, 'server'),
                sets=sets,
                speed=self.cfg.gt(provider, 'speed'),
                slow=self.cfg.gt(provider, 'slow'),
                yandex_api=self.cfg.yandex_api(provider)
            )
        except(RuntimeError, TTS.gTTSError, ValueError) as e:
            self._synthesis_error(provider, key, e)
            self._file_path = self.cfg.path['tts_error']
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
            self._synthesis_error(provider, key, e)
        for fp in write_to:
            fp.close()

    def _synthesis_error(self, prov, key, e):
        self.log(LNG['err_synthesis'].format(prov, utils.mask_off(key), e), logger.CRIT)


class SpeechToText:
    def __init__(self, cfg, log, owner: Owner):
        self.log = log
        self._cfg = cfg
        self.own = owner
        self.sys_say = Phrases(log, cfg)
        self._lock = threading.Lock()
        self._work = True
        self._start_stt_event = owner.registration('start_stt_event')
        self._stop_stt_event = owner.registration('stop_stt_event')
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
            self._start_stt_event()
            try:
                msg = self._listen_and_take(hello, deaf, voice)
            finally:
                self._stop_stt_event()
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
                self.own.say(say, blocking=120 if self._cfg.gts('blocking_listener') else 0)
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
            self.own.play(self._cfg.path['ding'], lvl, blocking=2)
        else:
            self.own.set_lvl(lvl)
            self.own.kill_popen()
        self.log('audio devices: {}'.format(pyaudio.PyAudio().get_device_count() - 1), logger.DEBUG)

        hello = hello or self.sys_say.hello
        file_path = self.own.tts(hello) if not voice and hello else None

        if self._cfg.gts('blocking_listener'):
            audio, record_time, energy_threshold = self._block_listen(hello, lvl, file_path)
        else:
            audio, record_time, energy_threshold = self._non_block_listen(hello, lvl, file_path)

        self.log(LNG['record_for'].format(utils.pretty_time(record_time)), logger.INFO)
        # Выключаем монопольный режим
        self.own.clear_lvl()

        if self._cfg.gts('alarmstt'):
            self.own.play(self._cfg.path['dong'])
        if audio is not None:
            commands = self.voice_recognition(audio)

        if commands:
            msg = ''
            if energy_threshold:
                msg = ', energy_threshold={}'.format(int(energy_threshold))
            self.log(LNG['recognized'].format(commands, msg), logger.INFO)
        return commands

    def _non_block_listen(self, hello, lvl, file_path):
        max_play_time = 120  # максимальное время воспроизведения приветствия
        max_wait_time = 10  # ожидание после приветствия

        listener = self.own.background_listen()

        if self._cfg.gts('alarmtts') and not hello:
            self.own.play(self._cfg.path['dong'], lvl)

        start_wait = time.time()
        if file_path:
            self.own.play(file_path, lvl)

        # Начинаем фоновое распознавание голосом после того как запустился плей.
        listener.start()
        self.own.record_callback(True)
        if file_path:
            while listener.work() and self.own.really_busy() and \
                    time.time() - start_wait < max_play_time and self._work:
                # Ждем пока время не выйдет, голос не распознался и файл играет
                time.sleep(0.01)
        self.own.quiet()

        start_wait2 = time.time()
        while listener.work() and time.time() - start_wait2 < max_wait_time and self._work:
            # ждем еще секунд 10
            time.sleep(0.01)

        record_time = time.time() - start_wait
        listener.stop()
        self.own.record_callback(False)
        return listener.audio, record_time, listener.energy_threshold

    def _block_listen(self, hello, lvl, file_path, self_call=False):
        r = sr.Recognizer(self.own.record_callback, self._cfg.gt('listener', 'silent_multiplier'))
        mic = sr.Microphone(device_index=self.get_mic_index())
        if self._cfg.gts('alarmtts') and not hello:
            self.own.play(self._cfg.path['dong'], lvl, blocking=2)
        detector = self.own.get_detector(mic)
        if file_path:
            self.own.play(file_path, lvl, blocking=120)

        audio, record_time, energy_threshold = self.own.listener_listen(r, mic, detector)
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
        self._start_stt_event()
        try:
            return self._voice_record(hello, save_to, convert_rate, convert_width)
        finally:
            self.own.clear_lvl()
            self._stop_stt_event()
            self._lock.release()

    def _voice_record(self, hello: str, save_to: str, convert_rate=None, convert_width=None):
        lvl = 5  # Включаем монопольный режим

        file_path = self.own.tts(hello)()
        self.own.say(file_path, lvl, True, is_file=True, blocking=120)
        r = sr.Recognizer()
        mic = sr.Microphone(device_index=self.get_mic_index())
        detector = self.own.get_detector(mic)
        self.own.play(self._cfg.path['ding'], lvl, blocking=3)
        with mic as source:
            record_time = time.time()
            try:
                adata = r.listen1(source=source, detector=detector, timeout=5, phrase_time_limit=8)
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

    def voice_recognition(self, audio, quiet: bool=False, fusion=None) -> str:
        if isinstance(audio, StreamRecognition) and fusion is None:
            return audio.text
        self.own.speech_recognized(True)
        try:
            return self._voice_recognition(audio, quiet, fusion)
        finally:
            self.own.speech_recognized(False)

    def _voice_recognition(self, audio, quiet: bool=False, fusion=None) -> str:
        prov = self._cfg.gts('providerstt', 'unset')
        if not STT.support(prov):
            self.log(LNG['err_unknown_prov'].format(prov), logger.CRIT)
            return ''
        self.log(LNG['recognized_from'].format(prov), logger.DEBUG)
        wtime = time.time()
        try:
            command = STT.GetSTT(
                prov,
                audio_data=audio,
                key=self._cfg.key(prov, 'apikeystt'),
                lang=LANG_CODE['IETF'],
                url=self._cfg.gt(prov, 'server'),
                yandex_api=self._cfg.yandex_api(prov)
            )
        except STT.UnknownValueError:
            command = ''
        except (STT.RequestError, RuntimeError) as e:
            if not quiet:
                self.own.say(LNG['err_stt_say'])
            self.log(LNG['err_stt_log'].format(e), logger.ERROR)
            return ''
        if fusion:
            wtime = fusion()
        self.log(LNG['recognized_for'].format(utils.pretty_time(time.time() - wtime)), logger.DEBUG)
        return command or ''

    def phrase_from_files(self, files: list):
        if not files:
            return '', 0
        workers = [RecognitionWorker(self._voice_recognition, file) for file in files]
        result = [worker.get for worker in workers]
        del workers
        # Фраза с 50% + 1 побеждает
        consensus = len(result) // 2 + 1
        phrase = ''
        match_count = 0
        for say in result:
            if not say:
                continue
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
        self._result = self._voice_recognition(adata, True)

    @property
    def get(self):
        super().join()
        return self._result


class Phrases:
    def __init__(self, log, cfg):
        name = 'phrases_{}'.format(cfg.language_name())
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
