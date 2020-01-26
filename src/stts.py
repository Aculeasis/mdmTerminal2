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
from languages import STTS as LNG
from lib.audio_utils import StreamRecognition
from owner import Owner


class TextToSpeech:
    def __init__(self, cfg, log):
        self._log = log
        self.cfg = cfg

    def tts(self, msg, realtime: bool = True):
        if callable(msg):
            # Audio already synthesized
            return msg
        return _TTSWorker(self.cfg, self._log, msg, realtime).get


class _TTSWorker(threading.Thread):
    WAIT = 600

    def __init__(self, cfg, log, msg, realtime):
        super().__init__(name='TTSWorker')
        self.cfg = cfg
        self.log = log
        self._msg = str(msg)
        self._provider = msg.provider if isinstance(msg, utils.TextBox) else None
        self._provider = self._provider or self.cfg.gts('providertts')
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
        if not TTS.support(self._provider) :
            self.log(LNG['unknown_prov'].format(self._provider), logger.CRIT)
            self._file_path = self.cfg.path['tts_error']
            return self._unlock()
        msg = LNG['for_time'].format(*self._generating(), self._file_path)
        self.log(msg, logger.DEBUG if self._realtime else logger.INFO)

    def _generating(self):
        sha1 = hashlib.sha1(self._msg.encode()).hexdigest()
        ext = 'mp3' if self.cfg.yandex_api(self._provider) != 2 else 'opus'
        find_part = ''.join(('_', sha1, '.'))
        rname = find_part + ext
        use_cache = self.cfg.gt('cache', 'tts_size', 50) > 0
        msg_gen = '\'{}\' '.format(self._msg)

        if self._realtime:
            self.log('say {}'.format(msg_gen), logger.INFO)
            msg_gen = ''

        if use_cache and self._found_in_cache(find_part, ext):
            self._unlock()
            work_time = time.time() - self._start_time
            action = LNG['action_cache'].format(msg_gen)
            time_diff = ''
        else:
            if not use_cache and self._provider in ('rhvoice-rest', 'rhvoice'):
                ext = 'wav'
                self._buff_size *= 4
            self._file_path = os.path.join(self.cfg.gt('cache', 'path'), self._provider + rname) if use_cache else \
                '<{}><{}>'.format(sha1, ext)
            self._tts_gen(self._file_path if use_cache else None, ext, self._msg)
            self._unlock()
            work_time = time.time() - self._start_time
            action = LNG['action_gen'].format(msg_gen, self._provider)
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

    def _found_in_cache(self, rname: str, ext: str):
        prov_priority = self.cfg.gt('cache', 'tts_priority', '')
        self._file_path = None
        if TTS.support(prov_priority):  # Приоритет
            self._file_path = self._file_check(prov_priority, rname, ext)

        if not self._file_path and prov_priority != self._provider:  # Обычная, второй раз не чекаем
            self._file_path = self._file_check(self._provider, rname, ext)

        if not self._file_path and prov_priority == '*':  # Ищем всех
            for key in TTS.PROVIDERS:
                if key != self._provider:
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

    def _tts_gen(self, file, format_, msg: str):
        key = None
        sets = utils.rhvoice_rest_sets(self.cfg[self._provider]) if self._provider == 'rhvoice-rest' else {}
        try:
            key = self.cfg.key(self._provider, 'apikeytts')
            tts = TTS.GetTTS(
                self._provider,
                text=msg,
                buff_size=self._buff_size,
                speaker=self.cfg.gt(self._provider, 'speaker'),
                audio_format=format_,
                key=key,
                lang=self.cfg.tts_lang(self._provider),
                emotion=self.cfg.gt(self._provider, 'emotion'),
                url=self.cfg.gt(self._provider, 'server'),
                sets=sets,
                speed=self.cfg.gt(self._provider, 'speed'),
                slow=self.cfg.gt(self._provider, 'slow'),
                yandex_api=self.cfg.yandex_api(self._provider)
            )
        except(RuntimeError, TTS.gTTSError, ValueError, AssertionError) as e:
            self._synthesis_error(key, e)
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
            self._synthesis_error(key, e)
        for fp in write_to:
            fp.close()

    def _synthesis_error(self, key, e):
        self.log(LNG['err_synthesis'].format(self._provider, utils.mask_off(key), e), logger.CRIT)


class SpeechToText:
    def __init__(self, cfg, log, owner: Owner):
        self.log = log
        self.cfg = cfg
        self.own = owner
        self.sys_say = Phrases(log, cfg)
        self._lock = threading.Lock()
        self._work = True
        self._start_stt_event = owner.registration('start_stt_event')
        self._stop_stt_event = owner.registration('stop_stt_event')
        try:
            self.max_mic_index = len(sr.Microphone().list_microphone_names()) - 1
            try:
                with sr.Microphone(device_index=self.get_mic_index()) as _:
                    pass
            except OSError as e:
                if e.errno == -9996:
                    raise
        except OSError as e:
            self.log('Error get list microphones: {}'.format(e), logger.CRIT)
            self.max_mic_index = -2

    def reload(self):
        self.sys_say = Phrases(self.log, self.cfg)

    def start(self):
        self._work = True
        self.log('start.', logger.INFO)
        self._select_sample_rate()
        self._print_mic_info()

    def stop(self):
        self._work = False
        self.log('stop.', logger.INFO)

    def busy(self):
        return self._lock.locked() and self._work

    def listen(self, hello: str = '', deaf: bool = True, voice: bool = False) -> tuple:
        msg, rms = '', None
        if not self._work:
            pass
        elif self.max_mic_index != -2:
            self._lock.acquire()
            self._start_stt_event()
            try:
                msg, rms = self._listen_and_take(hello, deaf, voice)
            finally:
                self._stop_stt_event()
                self._lock.release()
        else:
            self.log(LNG['no_mics'], logger.ERROR)
            msg = LNG['no_mics']
        return msg, rms

    def _listen_and_take(self, hello, deaf, voice) -> tuple:
        ask_me_again = self.cfg.get_uint('ask_me_again')
        msg, rms = self._listen(hello, voice)
        again = msg is None and ask_me_again > 0

        while again:  # Переспрашиваем
            self.own.ask_again_callback()
            msg, rms = self._listen(self.sys_say.ask, False)
            ask_me_again -= 1
            again = msg is None and ask_me_again
        if msg is None and deaf:
            say = self.sys_say.deaf
            if say:
                self.own.say(say, blocking=120 if self.cfg.gts('blocking_listener') else 0)
        return msg or '', rms

    def get_mic_index(self):
        device_index = self.cfg.gts('mic_index', -1)
        if device_index > self.max_mic_index:
            if self.max_mic_index >= 0:
                mics = LNG['mics_to'].format(self.max_mic_index + 1, self.max_mic_index)
            else:
                mics = LNG['no_mics']
            self.log(LNG['wrong_mic_index'].format(device_index, mics), logger.WARN)
            return None
        return None if device_index < 0 else device_index

    def _listen(self, hello: str, voice) -> tuple:
        lvl = 5  # Включаем монопольный режим
        commands = None

        if self.cfg.gts('alarmkwactivated'):
            self.own.play(self.cfg.path['ding'], lvl, blocking=2)
        else:
            self.own.set_lvl(lvl)
            self.own.kill_popen()
        self.log('audio devices: {}'.format(pyaudio.PyAudio().get_device_count() - 1), logger.DEBUG)

        hello = hello or self.sys_say.hello
        file_path = self.own.tts(hello) if not voice and hello else None

        if self.cfg.gts('blocking_listener'):
            audio, record_time, energy, rms = self._block_listen(hello, lvl, file_path)
        else:
            audio, record_time, energy, rms = self._non_block_listen(hello, lvl, file_path)

        self.log(LNG['record_for'].format(utils.pretty_time(record_time)), logger.INFO)
        # Выключаем монопольный режим
        self.own.clear_lvl()

        if self.cfg.gts('alarmstt'):
            self.own.play(self.cfg.path['dong'])
        if audio is not None:
            commands = self.voice_recognition(audio)

        if commands:
            self.log(utils.recognition_msg(commands, energy, rms), logger.INFO)
        return commands, rms

    def _non_block_listen(self, hello, lvl, file_path):
        max_play_time = 120  # максимальное время воспроизведения приветствия
        max_wait_time = 10  # ожидание после приветствия

        listener = self.own.background_listen()

        start_wait = time.time()
        if file_path:
            self.own.say(file_path, lvl, False if hello else None, is_file=True)
        elif self.cfg.gts('alarmtts') and not hello:
            self.own.say(self.cfg.path['dong'], lvl, False, is_file=True)

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
        return listener.audio, record_time, listener.energy_threshold, listener.rms

    def _block_listen(self, hello, lvl, file_path, self_call=False):
        r = sr.Recognizer(self.own.record_callback, self.cfg.gt('listener', 'silent_multiplier'))
        mic = sr.Microphone(device_index=self.get_mic_index())
        alarm = self.cfg.gts('alarmtts') and not hello

        if alarm or file_path:
            self.own.say_callback(True)
        try:
            if alarm:
                self.own.play(self.cfg.path['dong'], lvl, blocking=2)
            vad = self.own.get_vad_detector(mic)
            if file_path:
                self.own.play(file_path, lvl, blocking=120)
        finally:
            if alarm or file_path:
                self.own.say_callback(False)

        audio, record_time, energy_threshold, rms = self.own.listener_listen(r, mic, vad)
        if record_time < 0.5 and not self_call:
            # Если от инициализации микрофона до записи прошло больше 20-35 сек, то запись ломается
            # Игнорируем полученную запись и запускаем новую, без приветствий
            self.log('Long ask fix!', logger.DEBUG)
            return self._block_listen(hello=True, lvl=lvl, file_path=None, self_call=True)
        else:
            return audio, record_time, energy_threshold, rms

    def voice_record(self, hello: str or None, save_to: str, convert_rate=None, convert_width=None, limit=8):
        if self.max_mic_index == -2:
            self.log(LNG['no_mics'], logger.ERROR)
            return LNG['no_mics']
        self._lock.acquire()
        self._start_stt_event()
        try:
            return self._voice_record(hello, save_to, convert_rate, convert_width, limit)
        finally:
            self.own.clear_lvl()
            self._stop_stt_event()
            self._lock.release()

    def _voice_record(self, hello: str or None, save_to: str, convert_rate, convert_width, limit):
        lvl = 5  # Включаем монопольный режим

        if hello is not None:
            self.own.say(self.own.tts(hello)(), lvl, True, is_file=True, blocking=120)
        else:
            self.own.set_lvl(lvl)
        r = sr.Recognizer()
        mic = sr.Microphone(device_index=self.get_mic_index())
        vad = self.own.get_vad_detector(mic)
        self.own.play(self.cfg.path['ding'], lvl, blocking=3)
        with mic as source:
            record_time = time.time()
            try:
                adata = r.listen1(source=source, vad=vad, timeout=5, phrase_time_limit=limit)
            except sr.WaitTimeoutError as e:
                return str(e)
            if time.time() - record_time < 0.5:
                return LNG['err_voice_record']
        try:
            os.makedirs(os.path.dirname(save_to), exist_ok=True)
            with open(save_to, "wb") as f:
                f.write(adata.get_wav_data(convert_rate, convert_width))
        except IOError as err:
            return str(err)
        else:
            return None

    def voice_recognition(self, audio, quiet: bool = False, fusion=None) -> str:
        if isinstance(audio, StreamRecognition) and fusion is None:
            return audio.text
        self.own.speech_recognized(True)
        try:
            return self._voice_recognition(audio, quiet, fusion)
        finally:
            self.own.speech_recognized(False)

    def _voice_recognition(self, audio, quiet: bool = False, fusion=None, provider=None) -> utils.TextBox:
        def say(text: str):
            if not quiet:
                self.own.say(text)
        quiet = quiet or not self.cfg.gts('say_stt_error')
        prov = provider or self.cfg.gts('providerstt', 'unset')
        if not self.own.is_stt_provider(prov):
            self.log(LNG['err_unknown_prov'].format(prov), logger.CRIT)
            say(LNG['err_unknown_prov'].format(''))
            return utils.TextBox('', prov)
        self.log(LNG['recognized_from'].format(prov), logger.DEBUG)
        wtime = time.time()
        key = None
        try:
            key = self.cfg.key(prov, 'apikeystt')
            command = STT.GetSTT(
                prov,
                audio_data=audio,
                key=key,
                lang=self.cfg.stt_lang(prov),
                url=self.cfg.gt(prov, 'server'),
                yandex_api=self.cfg.yandex_api(prov),
                grpc=self.cfg.gt(prov, 'grpc'),
            ).text()
        except STT.UnknownValueError:
            command = ''
        except (STT.RequestError, RuntimeError, AssertionError) as e:
            say(LNG['err_stt_say'])
            self.log(LNG['err_stt_log'].format(prov, utils.mask_off(key), e), logger.ERROR)
            return utils.TextBox('', prov)
        if fusion:
            wtime = fusion()
        w_time = time.time() - wtime
        self.log(LNG['recognized_for'].format(utils.pretty_time(w_time)), logger.DEBUG)
        return utils.TextBox(command or '', prov, w_time)

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

    def multiple_recognition(self, file_or_adata, providers: list) -> list:
        if not providers:
            return []
        adata = adata_from_file(file_or_adata)
        workers = [RecognitionWorker(self._voice_recognition, adata, provider) for provider in providers]
        return [worker.get for worker in workers]

    def _print_mic_info(self):
        if self.max_mic_index < 0:
            return
        index = self.cfg.gts('mic_index', -1)
        name = sr.Microphone.get_microphone_name(index if index > -1 else None)
        self.log('Microphone: "{}: {}"'.format(index if index > -1 else 'Default', name), logger.INFO)

    def _select_sample_rate(self):
        try:
            self._sample_rate_tester()
        except RuntimeError as e:
            self.log(e, logger.CRIT)
            time.sleep(0.2)
            raise RuntimeError()

    def _sample_rate_tester(self):
        def tester():
            rates = (32000, 8000, 48000, 44100, None)
            if self.max_mic_index == -2:
                return
            if self._test_rate():
                return
            for rate in rates:
                msg = 'Microphone does not support sample rate {}, fallback to {}'.format(
                    sr.Microphone.DEFAULT_RATE, rate)
                self.log(msg, logger.WARN)
                sr.Microphone.DEFAULT_RATE = rate
                if self._test_rate():
                    return
            raise RuntimeError('Microphone is broken. Supported sample rate not found')
        try:
            tester()
        except RuntimeError as e:
            self.max_mic_index = -2
            self.log(e, logger.ERROR)

    def _test_rate(self):
        try:
            with sr.Microphone(device_index=self.get_mic_index()) as _:
                pass
        except OSError as e:
            if e.errno == -9997:
                return False
            raise RuntimeError('Microphone is broken: {}'.format(e))
        else:
            return True


class RecognitionWorker(threading.Thread):
    def __init__(self, voice_recognition, file_or_adata, provider=None):
        super().__init__()
        self._voice_recognition = voice_recognition
        self._file_or_adata = file_or_adata
        self._provider = provider
        self._result = utils.TextBox('', provider)
        self.start()

    def run(self):
        self._result = self._voice_recognition(adata_from_file(self._file_or_adata), True, provider=self._provider)

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
        return self._choice('hello')

    @property
    def deaf(self) -> str:
        return self._choice('deaf')

    @property
    def ask(self) -> str:
        return self._choice('ask')

    @property
    def chance(self) -> bool:
        return random.SystemRandom().randint(1, 100) <= self._phrases['chance']

    def _choice(self, name: str) -> str:
        return random.SystemRandom().choice(self._phrases[name])


def adata_from_file(file_or_adata: str or sr.AudioData) -> sr.AudioData:
    if isinstance(file_or_adata, sr.AudioData):
        return file_or_adata
    else:
        with wave.open(file_or_adata, 'rb') as fp:
            return sr.AudioData(fp.readframes(fp.getnframes()), fp.getframerate(), fp.getsampwidth())
