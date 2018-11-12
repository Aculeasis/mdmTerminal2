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
import lib.sr_proxifier as sr
import logger
import utils


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
    PROVIDERS = {
        'google': 'ru',
        'yandex': 'ru-RU',
        'rhvoice-rest': '',
        'rhvoice': '',
    }

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
        self.start_time = time.time()
        self.start()

    def get(self):
        self.event.wait(600)
        self._unlock()
        return self.file_path, self._stream, self._ext

    def run(self):
        wtime = time.time()
        sha1 = hashlib.sha1(self.msg.encode()).hexdigest()
        provider = self.cfg.get('providertts', 'google')
        rname = '_'+sha1 + '.mp3'
        if self.realtime:
            self.log('say \'{}\''.format(self.msg), logger.INFO)
            msg_gen = ''
        else:
            msg_gen = '\'{}\' '.format(self.msg)
        use_cache = self.cfg['cache'].get('tts_size', 50) > 0

        self.file_path = self._find_in_cache(rname, provider) if use_cache else None
        if self.file_path:
            self._unlock()
            work_time = time.time() - wtime
            action = '{}найдено в кэше'.format(msg_gen)
            time_diff = ''
        else:
            format_ = 'mp3' if use_cache or provider in ['google', 'yandex'] else 'wav'
            self.file_path = os.path.join(self.cfg.path['tts_cache'], provider + rname) if use_cache else \
                '<{}><{}>'.format(sha1, format_)
            self._tts_gen(self.file_path if use_cache else None, format_, self.msg)
            self._unlock()
            work_time = time.time() - wtime
            action = '{}сгенерированно {}'.format(msg_gen, provider)
            reply = utils.pretty_time(self.work_time) if self.work_time is not None else 'NaN'
            diff = utils.pretty_time(work_time - self.work_time) if self.work_time is not None else 'NaN'
            time_diff = ' [reply:{}, diff:{}]'.format(reply, diff)
        self.log(
            '{} за {}{}: {}'.format(action, utils.pretty_time(work_time), time_diff, self.file_path),
            logger.DEBUG if self.realtime else logger.INFO
        )

    def _unlock(self):
        if self.work_time is None:
            self.work_time = time.time() - self.start_time
        self.event.set()

    def _find_in_cache(self, rname: str, prov: str):
        prov_priority = self.cfg['cache'].get('tts_priority', '')
        file = None
        if prov_priority in self.PROVIDERS:  # Приоритет
            file = self._file_check(rname, prov_priority)

        if not file and prov_priority != prov:  # Обычная, второй раз не чекаем
            file = self._file_check(rname, prov)

        if not file and prov_priority == '*':  # Ищем всех
            for key in self.PROVIDERS:
                if key != prov:
                    file = self._file_check(rname, key)
                if file:
                    break
        return file

    def _file_check(self, rname, prov):
        file = os.path.join(self.cfg.path['tts_cache'], prov + rname)
        return file if os.path.isfile(file) else ''

    def _tts_gen(self, file, format_, msg: str):
        prov = self.cfg.get('providertts', 'unset')
        key = self.cfg.key(prov, 'apikeytts')
        if TTS.support(prov):
            sets = utils.rhvoice_rest_sets(self.cfg[prov]) if prov == 'rhvoice-rest' else None
            try:
                tts = TTS.GetTTS(
                    prov,
                    text=msg,
                    speaker=self.cfg.get(prov, {}).get('speaker'),
                    audio_format=format_,
                    key=key,
                    lang=self.PROVIDERS[prov],
                    emotion=self.cfg.get(prov, {}).get('emotion'),
                    url=self.cfg.get(prov, {}).get('server'),
                    sets=sets
                )
            except RuntimeError as e:
                self._synthesis_error(prov, key, e)
                self.file_path = self.cfg.path['tts_error']
                return
        else:
            self.log('Неизвестный провайдер: {}'.format(prov), logger.CRIT)
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
        except RuntimeError as e:
            self._synthesis_error(prov, key, e)
        for fp in write_to:
            fp.close()
        return

    def _synthesis_error(self, prov, key, e):
        self.log('Ошибка синтеза речи от {}, ключ \'{}\'. ({})'.format(prov, key, e), logger.CRIT)


class SpeechToText:
    HELLO = ['Привет', 'Слушаю', 'На связи', 'Привет-Привет']
    DEAF = ['Я ничего не услышала', 'Вы ничего не сказали', 'Ничего не слышно', 'Не поняла']
    ASK_AGAIN = 'Ничего не слышно, повторите ваш запрос'

    def __init__(self, cfg, play_, log, tts):
        self.log = log
        self._cfg = cfg
        self._lock = threading.Lock()
        self._work = True
        self._play = play_
        self._tts = tts
        try:
            self.max_mic_index = len(sr.Microphone().list_microphone_names()) - 1
        except OSError as e:
            self.log('Error get list microphones: {}'.format(e), logger.CRIT)
            self.max_mic_index = -2

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
            self.log('Микрофоны не найдены', logger.ERROR)
            msg = 'Микрофоны не найдены'
        return msg

    def _listen_and_take(self, hello, deaf, voice) -> str:
        ask_me_again = self._cfg.get_uint('ask_me_again')
        msg = self._listen(hello, voice)

        while msg is None and ask_me_again:  # Переспрашиваем
            ask_me_again -= 1
            msg = self._listen(self.ASK_AGAIN, False)
        if msg is None and deaf:
            self._say_deaf()
        return msg or ''

    def _say_deaf(self):
        self._play.say(random.SystemRandom().choice(self.DEAF))

    def get_mic_index(self):
        device_index = self._cfg.get('mic_index', -1)
        if device_index > self.max_mic_index:
            if self.max_mic_index >= 0:
                mics = 'Доступны {}, от 0 до {}.'.format(self.max_mic_index + 1, self.max_mic_index)
            else:
                mics = 'Микрофоны не найдены.'
            self.log('Не верный индекс микрофона {}. {}'.format(device_index, mics), logger.WARN)
            return None
        return None if device_index < 0 else device_index

    def _listen(self, hello: str, voice) -> str or None:
        lvl = 5  # Включаем монопольный режим
        commands = None

        if self._cfg['alarmkwactivated']:
            self._play.play(self._cfg.path['ding'], lvl, wait=0.01, blocking=2)
        else:
            self._play.set_lvl(lvl)
            self._play.kill_popen()
        self.log('audio devices: {}'.format(pyaudio.PyAudio().get_device_count() - 1), logger.DEBUG)

        file_path = self._tts(random.SystemRandom().choice(self.HELLO) if not hello else hello) if not voice else None

        if self._cfg.get('blocking_listener'):
            audio, recognizer, record_time = self._block_listen(hello, lvl, file_path)
        else:
            audio, recognizer, record_time = self._non_block_listen(hello, lvl, file_path)

        self.log('Голос записан за {}'.format(utils.pretty_time(record_time)), logger.INFO)
        # Выключаем монопольный режим
        self._play.clear_lvl()

        if self._cfg['alarmstt']:
            self._play.play(self._cfg.path['dong'])
        if audio is not None:
            commands = self._voice_recognition(audio, recognizer)

        if commands:
            self.log('Распознано: {}'.format(commands), logger.INFO)
        return commands

    def _non_block_listen(self, hello, lvl, file_path):
        max_play_time = 120  # максимальное время воспроизведения приветствия
        max_wait_time = 10  # ожидание после приветствия

        r = sr.Recognizer()
        mic = sr.Microphone(device_index=self.get_mic_index())

        with mic as source:  # Слушаем шум 1 секунду, потом распознаем, если раздажает задержка можно закомментировать.
            r.adjust_for_ambient_noise(source)

        if self._cfg['alarmtts'] and not hello:
            self._play.play(self._cfg.path['dong'], lvl)

        start_wait = time.time()
        if file_path:
            self._play.play(file_path, lvl)

        # Начинаем фоновое распознавание голосом после того как запустился плей.
        listener = NonBlockListener(r=r, source=mic, phrase_time_limit=20)
        if file_path:
            while listener.work() and self._play.really_busy() and time.time() - start_wait < max_play_time and self._work:
                # Ждем пока время не выйдет, голос не распознался и файл играет
                time.sleep(0.01)
        self._play.quiet()

        start_wait2 = time.time()
        while listener.work() and time.time() - start_wait2 < max_wait_time and self._work:
            # ждем еще секунд 10
            time.sleep(0.01)

        record_time = time.time() - start_wait
        listener.stop()
        return listener.audio, listener.recognizer, record_time

    def _block_listen(self, hello, lvl, file_path):
        with sr.Microphone() as source:
            r = sr.Recognizer()

            if self._cfg['alarmtts'] and not hello:
                self._play.play(self._cfg.path['dong'], lvl, wait=0.01, blocking=2)

            if file_path:
                self._play.play(file_path, lvl, wait=0.01, blocking=120)

            r.adjust_for_ambient_noise(source)

            record_time = time.time()
            try:
                audio = r.listen(source, timeout=10, phrase_time_limit=15)
            except sr.WaitTimeoutError:
                audio = None
            record_time = time.time() - record_time

            return audio, r, record_time

    def voice_record(self, hello: str, save_to: str, convert_rate=None, convert_width=None):
        if self.max_mic_index == -2:
            self.log('Микрофоны не найдены', logger.ERROR)
            return 'Микрофоны не найдены'
        self._lock.acquire()
        try:
            return self._voice_record(hello, save_to, convert_rate, convert_width)
        finally:
            self._play.clear_lvl()
            self._lock.release()

    def _voice_record(self, hello: str, save_to: str, convert_rate=None, convert_width=None):
        lvl = 5  # Включаем монопольный режим

        file_path = self._tts(hello)()
        r = sr.Recognizer()

        self._play.say(file_path, lvl, True, is_file=True)
        self._play.play(self._cfg.path['ding'], lvl)

        start_time = time.time()
        while self._play.really_busy() and time.time() - start_time < 30 and self._work:
            time.sleep(0.01)

        # Пишем
        with sr.Microphone(device_index=self.get_mic_index()) as mic:
            try:
                adata = r.listen(source=mic, timeout=5, phrase_time_limit=3)
            except sr.WaitTimeoutError as e:
                return str(e)
        try:
            with open(save_to, "wb") as f:
                f.write(adata.get_wav_data(convert_rate, convert_width))
        except IOError as err:
            return str(err)
        else:
            return None

    def _voice_recognition(self, audio, recognizer, quiet=False) -> str or None:
        prov = self._cfg.get('providerstt', 'google')
        key = self._cfg.key(prov, 'apikeystt')
        self.log('Для распознования используем {}'.format(prov), logger.DEBUG)
        wtime = time.time()
        try:
            if prov == 'google':
                command = recognizer.recognize_google(audio, language='ru-RU')
            elif prov == 'wit.ai':
                command = recognizer.recognize_wit(audio, key=key)
            elif prov == 'microsoft':
                command = recognizer.recognize_bing(audio, key=key)
            elif prov == 'pocketsphinx-rest':
                command = STT.PocketSphinxREST(
                    audio_data=audio,
                    url=self._cfg.get(prov, {}).get('server', 'http://127.0.0.1:8085')
                ).text()
            elif prov == 'yandex':
                command = STT.Yandex(audio_data=audio, key=key).text()
            else:
                self.log('Ошибка распознавания - неизвестный провайдер {}'.format(prov), logger.CRIT)
                return ''
        except (sr.UnknownValueError, STT.UnknownValueError):
            return None
        except (sr.RequestError, RuntimeError) as e:
            if not quiet:
                self._play.say('Произошла ошибка распознавания')
            self.log('Произошла ошибка  {}'.format(e), logger.ERROR)
            return ''
        else:
            self.log('Распознано за {}'.format(utils.pretty_time(time.time() - wtime)), logger.DEBUG)
            return command or ''

    def phrase_from_files(self, files: list):
        if not files:
            return ''
        count = len(files)
        result = [None] * count
        for i in range(count):
            threading.Thread(target=self._recognition_worker, args=(files[i], result, i)).start()
        while [True for x in result if x is None]:
            time.sleep(0.05)
        # Фраза с 50% + 1 побеждает
        consensus = count // 2 + 1
        phrase = ''
        for say in result:
            if result.count(say) >= consensus:
                phrase = say
                break
        self.log('Распознано: {}. Консенсус: {}'.format(', '.join([str(x) for x in result]), phrase), logger.DEBUG)
        return phrase

    def _recognition_worker(self, file, result, i):
        r = sr.Recognizer()
        with wave.open(file, 'rb') as fp:
            adata = sr.AudioData(fp.readframes(fp.getnframes()), fp.getframerate(), fp.getsampwidth())
        say = self._voice_recognition(adata, r, True) or ''
        result[i] = say.strip()


class NonBlockListener:
    def __init__(self, r, source, phrase_time_limit):
        self.recognizer = None
        self.audio = None
        self.stop = r.listen_in_background(source, self._callback, phrase_time_limit=phrase_time_limit)

    def work(self):
        return self.audio is None

    def _callback(self, rec, audio):
        if self.work():
            self.audio = audio
            self.recognizer = rec




