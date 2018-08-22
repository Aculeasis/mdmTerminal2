#!/usr/bin/env python3

import hashlib
import os
import os.path
import random
import time


import pyaudio
import speech_recognition as sr
from gtts import gTTS

import logger
import utils
from lib import ya_tts
from lib import rhvoice_rest
import player


class TextToSpeech:
    PROVIDERS = {
        'google': 'ru',
        'yandex': 'ru-RU',
    }

    def __init__(self, cfg, log):
        self.log = log
        self._cfg = cfg

    def tts(self, msg, realtime: bool = True):
        wtime = time.time()
        sha1 = hashlib.sha1(msg.encode('utf-8')).hexdigest()
        provider = self._cfg.get('providertts', 'google')
        rname = '_'+sha1 + '.mp3'
        file_path = self._find_in_cache(rname, provider)
        if realtime:
            self.log('say \'{}\''.format(msg), logger.INFO)
            msg_gen = ''
        else:
            msg_gen = '\'{}\' '.format(msg)
        in_cache = False
        if file_path:
            action = '{}найдено в кэше'.format(msg_gen)
            in_cache = True
        else:
            file_path = os.path.join(self._cfg.path['tts_cache'], provider + rname)
            file_path = self._tts_gen(file_path, msg)
            action = '{}сгенерированно {}'.format(msg_gen, provider)
        self.log(
            '{} за {}: {}'.format(action, utils.pretty_time(time.time() - wtime), file_path),
            logger.DEBUG if realtime else logger.INFO
        )
        return file_path, in_cache

    def _find_in_cache(self, rname: str, prov: str):
        if not self._cfg['cache'].get('tts_size', 0):
            return ''

        prov_priority = self._cfg['cache'].get('tts_priority', '')
        file = ''
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
        file = os.path.join(self._cfg.path['tts_cache'], prov + rname)
        return file if os.path.isfile(file) else ''

    def _tts_gen(self, file: str, msg: str):
        prov = self._cfg.get('providertts', 'unset')
        key = self._cfg.get(prov, {}).get('apikeytts', None)
        try:
            if prov == 'google':
                tts = gTTS(text=msg, lang=self.PROVIDERS[prov])
            elif prov == 'yandex':
                tts = ya_tts.TTS(
                    text=msg,
                    speaker=self._cfg.get(prov, {}).get('speaker', 'alyss'),
                    audio_format='mp3',
                    key=key,
                    lang=self.PROVIDERS[prov],
                    emotion=self._cfg.get(prov, {}).get('emotion', 'good')
                )
            elif prov == 'rhvoice':
                tts = rhvoice_rest.TTS(
                    text=msg,
                    url=self._cfg.get(prov, {}).get('server', 'http://127.0.0.1:8080'),
                    voice=self._cfg.get(prov, {}).get('speaker', 'anna')
                )
            else:
                self.log('Неизвестный провайдер: {}'.format(prov), logger.CRIT)
                return self._cfg.path['tts_error']
        except (ya_tts.Error, rhvoice_rest.Error)as e:
            self.log('Ошибка синтеза речи от {}, ключ \'{}\'. ([{}]:{})'.format(
                prov, key, e.code, e.msg), logger.CRIT
            )
            return self._cfg.path['tts_error']
        tts.save(file)
        return file


class SpeechToText:
    HELLO = ['Привет', 'Слушаю', 'На связи', 'Привет-Привет']
    DEAF = ['Вы что то сказали?', 'Я ничего не услышала', 'Что Вы спросили?', 'Не поняла']

    def __init__(self, cfg, play_: player.Player, log):
        self.log = log
        self._cfg = cfg
        self._busy = False
        self._work = True
        self._play = play_
        self._max_mic_index = len(sr.Microphone().list_microphone_names()) - 1

    def start(self):
        self._work = True
        self.log('start.', logger.INFO)

    def stop(self):
        self._work = False
        self.log('stop.', logger.INFO)

    def busy(self):
        return self._busy and self._work

    def listen(self, hello: str = '', deaf: bool = True, voice: bool = False) -> str:
        while self.busy():
            time.sleep(0.01)
        if not self._work:
            return ''

        self._busy = True
        msg = self._listen(hello, deaf, voice)
        self._busy = False
        return msg

    def get_mic_index(self):
        device_index = self._cfg.get('mic_index', -1)
        if device_index > self._max_mic_index:
            if self._max_mic_index >= 0:
                mics = 'Доступны {}, от 0 до {}.'.format(self._max_mic_index + 1, self._max_mic_index)
            else:
                mics = 'Микрофоны не найдены.'
            self.log('Не верный индекс микрофона {}. {}'.format(device_index, mics), logger.WARN)
            return None
        return None if device_index < 0 else device_index

    def _listen(self, hello: str, deaf, voice) -> str:
        max_play_time = 120  # максимальное время воспроизведения приветствия
        max_wait_time = 10  # ожидание после приветствия
        lvl = 5  # Включаем монопольный режим

        # self._play.quiet()
        if self._cfg['alarmkwactivated']:
            self._play.play(self._cfg.path['ding'], lvl)
        self.log('audio devices: {}'.format(pyaudio.PyAudio().get_device_count() - 1), logger.DEBUG)

        file_path, _ = self._play.tts(random.SystemRandom().choice(self.HELLO) if not hello else hello)

        r = sr.Recognizer()
        mic = sr.Microphone(device_index=self.get_mic_index())

        with mic as source:  # Слушаем шум 1 секунду, потом распознаем, если раздажает задержка можно закомментировать.
            r.adjust_for_ambient_noise(source)

        if self._cfg['alarmtts'] and not hello:
            self._play.play(self._cfg.path['dong'], lvl)

        start_wait = time.time()
        if not voice:
            self._play.play(file_path, lvl)

        # Начинаем фоновое распознавание голосом после того как запустился плей.
        listener = NonBlockListener(r=r, source=mic, phrase_time_limit=20)
        if not voice:
            while listener.work() and self._play.popen_work() and time.time() - start_wait < max_play_time and self._work:
                # Ждем пока время не выйдет, голос не распознался и файл играет
                # TODO: Прервать если распознавание запустилось
                time.sleep(0.01)
        self._play.quiet()

        start_wait2 = time.time()
        while listener.work() and time.time() - start_wait2 < max_wait_time and self._work:
            # ждем еще секунд 10
            time.sleep(0.01)

        self.log('Голос записан за {}'.format(utils.pretty_time(time.time() - start_wait)), logger.INFO)
        listener.stop()

        # Выключаем монопольный режим
        self._play.clear_lvl()

        if listener.audio is None:
            if deaf:
                self._play.say(random.SystemRandom().choice(self.DEAF))
            commands = ''
        else:
            if self._cfg['alarmstt']:
                self._play.play(self._cfg.path['dong'])
            commands = self._voice_recognition(listener.audio, listener.recognizer, deaf)

        if commands:
            self.log('Распознано: {}'.format(commands), logger.INFO)
        return commands

    def voice_record(self, hello: str, save_to: str):
        lvl = 5  # Включаем монопольный режим

        file_path, _ = self._play.tts(hello)
        r = sr.Recognizer()
        # mic = sr.Microphone(device_index=self.get_mic_index())

        # self._play.quiet()
        self._play.play(self._cfg.path['ding'], lvl)
        self._play.play(file_path, lvl)

        start_time = time.time()
        while self._play.popen_work() and time.time() - start_time < 30 and self._work:
            time.sleep(0.01)

        # Пишем
        with sr.Microphone(device_index=self.get_mic_index()) as mic:
            adata = r.listen(source=mic, timeout=5, phrase_time_limit=3)

        self._play.clear_lvl()

        try:
            with open(save_to, "wb") as f:
                f.write(adata.get_wav_data())
        except IOError as err:
            return str(err)
        else:
            return None

    def _voice_recognition(self, audio, recognizer, deaf) ->str:
        prov = self._cfg.get('providerstt', 'google')
        key = self._cfg.get(prov, {}).get('apikeystt', '')
        self.log('Для распознования используем {}'.format(prov), logger.DEBUG)
        wtime = time.time()
        try:
            if prov == 'google':
                command = recognizer.recognize_google(audio, language='ru-RU')
            elif prov == 'wit.ai':
                command = recognizer.recognize_wit(audio, key=key)
            elif prov == 'microsoft':
                command = recognizer.recognize_bing(audio, key=prov)
            else:
                self.log('Ошибка распознавания - неизвестный провайдер {}'.format(prov), logger.CRIT)
                return ''
        except sr.UnknownValueError:
            if deaf:
                self._play.say(random.SystemRandom().choice(self.DEAF))
            return ''
        except sr.RequestError as e:
            self._play.say('Произошла ошибка распознавания')
            self.log('Произошла ошибка  {}'.format(e), logger.ERROR)
            return ''
        else:
            self.log('Распознано за {}'.format(utils.pretty_time(time.time() - wtime)), logger.DEBUG)
            return command


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




