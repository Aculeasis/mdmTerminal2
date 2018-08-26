#!/usr/bin/env python3


import queue
import hashlib
import time
import threading
import logger
import os
import subprocess
import stts
import mpd


class Player:
    PLAY = {
        '.mp3': ['mpg123', '-q'],
        '.wav': ['aplay', '-q'],
    }
    MAX_BUSY_WAIT = 120  # Макс время блокировки, потом отлуп. Поможет от возможных зависаний

    def __init__(self, cfg, logger_: logger.Logger):
        self._cfg = cfg
        self.log = logger_.add('Player')
        # 0 - играем в фоне, до 5 снимаем блокировку автоматически. 5 - монопольный режим, нужно снять блокировку руками
        self._lvl = 0
        self._work = False
        self._popen = None
        self._busy = False
        self._uid = 0
        self._last_activity = time.time()
        self.tts = stts.TextToSpeech(cfg, logger_.add('TTS')).tts

        self.mpd = MPDControl(self._cfg['mpd'], self.last_activity)
        self._lp_play = LowPrioritySay(self.busy, self.say, self.play, self.tts)

    def start(self):
        self._work = True
        self._lp_play.start()
        if self._cfg['mpd'].get('control', 0):
            msg = self.mpd.start()
            if msg:
                self.log('Ошибка подключения к MPD-серверу: {}'.format(msg), logger.ERROR)
                self.say('Ошибка подключения к MPD-серверу')
        self.log('start.', logger.INFO)

    def stop(self):
        self._work = False
        self.log('stopping...', logger.DEBUG)
        self._lvl = 100500
        self._lp_play.stop()

        count = 0
        while (self.popen_work()) and count < 1000:
            time.sleep(0.01)
            count += 1
        self.quiet()

        self._last_activity = 0  # Отжим паузы
        self.mpd.stop()

        self.log('stop.', logger.INFO)

    def set_lvl(self, lvl, uid):

        if lvl > 1:
            self._lp_play.clear()

        start_time = time.time()
        if lvl <= self.get_lvl():
                while self.busy() and time.time() - start_time < self.MAX_BUSY_WAIT:
                    pass
        if lvl >= self.get_lvl():
            self.set_busy(lvl, uid)
            return True
        return False

    def set_busy(self, lvl, uid):
        self._lvl = lvl
        self._uid = uid
        self._busy = True
        self.quiet()
        self._busy = True

    def get_lvl(self):
        if self._lvl < 5:
            if self.busy():
                return self._lvl
        else:
            return self._lvl
        return 0

    def clear_lvl(self):
        self._lvl = 0

    def busy(self):
        return self._work and (self.popen_work() or self._busy)

    def quiet(self):
        if self.popen_work():
            self._lp_play.clear()
            self._popen.kill()
            self._busy = False
            self.log('Stop playing', logger.DEBUG)

    def last_activity(self):
        if self.popen_work():
            self._last_activity = time.time()
        return self._last_activity

    def popen_work(self):
        return self._popen is not None and self._popen.poll() is None

    def play(self, file, lvl: int=2, wait=0):
        if not lvl:
            self.log('low play \'{}\' pause {}'.format(file, wait), logger.DEBUG)
            self._lp_play.play(file, wait)
            return

        uid = hashlib.sha256(str(time.time()).encode()).hexdigest()
        if not self.set_lvl(lvl, uid):
            return

        self._last_activity = time.time() + 3
        self.mpd.pause(True)

        time.sleep(0.01)
        if uid != self._uid:
            return
        self._play(file)

        self._last_activity = time.time() + wait
        if wait:
            time.sleep(wait)
        if uid != self._uid:
            return
        self._busy = False

    def say(self, msg: str, lvl: int=2, alarm=None, wait=0, is_file: bool = False):
        if not lvl:
            self.log('low say \'{}\' pause {}'.format(msg, wait), logger.DEBUG)
            self._lp_play.say(msg, wait, is_file)
            return

        uid = hashlib.sha256(str(time.time()).encode()).hexdigest()
        if not self.set_lvl(lvl, uid):
            return

        if alarm is None:
            alarm = self._cfg.get('alarmtts', 0)

        file = self.tts(msg)[0] if not is_file else msg
        if uid != self._uid:
            return
        self._last_activity = time.time() + 3
        self.mpd.pause(True)

        time.sleep(0.01)
        if alarm:
            if uid != self._uid:
                return
            self._play(self._cfg.path['dong'])
            try:
                self._popen.wait(2)
            except subprocess.TimeoutExpired:
                pass
        if uid != self._uid:
            return
        self._play(file)

        self._last_activity = time.time() + wait
        if wait:
            time.sleep(wait)

        if uid != self._uid:
            return
        self._busy = False

    def _play(self, path: str):
        if not os.path.isfile(path):
            return self.log('Файл {} не найден'.format(path), logger.ERROR)
        extension = os.path.splitext(path)[1]
        if extension not in self.PLAY:
            return self.log('Неизвестный тип файла: {}'.format(extension), logger.CRIT)
        cmd = self.PLAY[extension].copy()
        cmd.append(path)
        self.log('Играю {} ...'.format(path, logger.DEBUG))
        # TODO: Переделать на pyAudio. wave есть, а вот с mp3 сложнее
        self._popen = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)


class LowPrioritySay:
    TIMEOUT = 300

    def __init__(self, is_busy, say, play, tts):
        self._play = play
        self._say = say
        self._tts = tts
        self._is_busy = is_busy
        self._th = threading.Thread(target=self._loop)
        self._work = False
        self._queue_in = queue.Queue()
        self._quiet = False

    def stop(self):
        self._work = False
        self._th.join()

    def start(self):
        self._work = True
        self._th.start()

    def clear(self):
        self._quiet = True
        while self._work and not self._queue_in.empty():
            if not self._queue_in.empty():
                try:
                    self._queue_in.get_nowait()
                except queue.Empty:
                    continue

    def say(self, msg: str, wait: float or int=0, is_file: bool = False):
        self._put(1 if not is_file else 3, msg, wait)

    def play(self, file: str, wait: float or int=0):
        self._put(2, file, wait)

    def _put(self, action, target, wait):
        if self._work:
            self._queue_in.put_nowait([action, target, wait])

    def _loop(self):
        while self._work:
            if self._queue_in.empty() or self._is_busy():
                time.sleep(0.05)
                continue

            try:
                say = self._queue_in.get_nowait()
            except queue.Empty:
                pass
            else:
                if say[0] == 1:
                    self._say(msg=say[1], lvl=1, wait=say[2])
                elif say[0] == 2:
                    self._play(file=say[1], lvl=1, wait=say[2])
                elif say[0] == 3:
                    self._say(msg=say[1], lvl=1, wait=say[2], is_file=True)


def _auto_reconnect(func):
    def wrapper(*args):
        try:
            return func(*args)
        except (mpd.MPDError, IOError):
            args[0].connect()
            if not args[0].is_conn:
                return False
            else:
                return func(*args)
    return wrapper


class MPDControl:
    def __init__(self, cfg: dict, last_play):
        self.IP = cfg.get('ip', '127.0.0.1')
        self.PORT = cfg.get('port', 6600)
        self.RESUME_TIME = cfg.get('wait', 13)

        self._last_play = last_play
        self._th = threading.Thread(target=self._loop)
        self._work = False
        self._mpd = mpd.MPDClient(use_unicode=True)
        self._resume = False
        self.is_conn = False

    def connect(self):
        if self.is_conn:
            self._disconnect()
        try:
            self._mpd.connect(self.IP, self.PORT)
        except (mpd.MPDError, IOError) as e:
            self.is_conn = False
            return str(e)
        else:
            self.is_conn = True
            return ''

    def _disconnect(self):
        try:
            self._mpd.close()
        except (mpd.MPDError, IOError):
            pass
        try:
            self._mpd.disconnect()
        except (mpd.MPDError, IOError):
            self._mpd = mpd.MPDClient(use_unicode=True)
        finally:
            self.is_conn = False

    def allow(self):
        return self.is_conn and self._work

    def stop(self):
        if self._work:
            self._resume_check()
            self._work = False
            self._th.join()

    def start(self):
        msg = self.connect()
        if msg == '':
            self._work = True
            self._th.start()
        return msg

    def play(self, uri):
        if not self.allow():
            return
        self._mpd_add(uri)
        self._resume = False

    def pause(self, paused=None):
        if not self.allow():
            return
        if paused is None:
            self._resume = False
            self._mpd_pause()
        elif paused:
            if self._mpd_is_play():
                self._resume = True
                self._mpd_pause(1)
        else:
            self._resume = False
            self._mpd_pause(0)

    def _loop(self):
        ping = 0
        while self._work:
            ping += 1
            time.sleep(0.5)
            self._resume_check()
            if ping > 20:
                ping = 0
                self._mpd_ping()
        self._disconnect()

    def _resume_check(self):
        if self._resume and time.time() - self._last_play() > self.RESUME_TIME:
            self.pause(False)

    @_auto_reconnect
    def _mpd_pause(self, pause=None):
        if pause is not None:
            self._mpd.pause(pause)
        else:
            self._mpd.pause()

    @_auto_reconnect
    def _mpd_add(self, uri):
        self._mpd.clear()
        self._mpd.add(uri)
        self._mpd.play(0)

    @_auto_reconnect
    def _mpd_is_play(self):
        return self._mpd.status().get('state', 'stop') == 'play'

    @_auto_reconnect
    def _mpd_ping(self):
        self._mpd.ping()


