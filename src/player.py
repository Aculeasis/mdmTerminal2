#!/usr/bin/env python3


import os
import queue
import subprocess
import threading
import time

import logger
from languages import PLAYER as LNG
from lib import linux_play
from owner import Owner


class Player:
    MAX_BUSY_WAIT = 300  # Макс время блокировки, потом отлуп. Поможет от возможных зависаний

    def __init__(self, cfg, log, owner: Owner):
        self._cfg = cfg
        self.log = log
        self.own = owner
        # 0 - играем в фоне, до 5 снимаем блокировку автоматически. 5 - монопольный режим, нужно снять блокировку руками
        self._lvl = 0
        self._only_one = threading.Lock()
        self._work = False
        self._popen = None
        self._lp_play = LowPrioritySay(self.really_busy, self.say, self.play)

    def start(self):
        self._work = True
        self._lp_play.start()
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
        self.kill_popen()

        self.log('stop.', logger.INFO)

    def set_lvl(self, lvl):
        if lvl > 1:
            self._lp_play.clear()

        start_time = time.time()
        if lvl <= self.get_lvl():
                while self.busy() and time.time() - start_time < self.MAX_BUSY_WAIT:
                    time.sleep(0.01)
        if lvl >= self.get_lvl():
            self._lvl = lvl
            self.quiet()
            return True
        self._only_one.release()
        return False

    def get_lvl(self):
        if self._lvl < 5:
            if self.busy():
                return self._lvl
        else:
            return self._lvl
        return 0

    def clear_lvl(self):
        self._lvl = 0

    def noising(self):
        # Плеер шумит, шумел только что или скоро начнет шуметь.
        return self.really_busy() or self.own.mpd_plays

    def busy(self):
        return self.popen_work() and self._work

    def really_busy(self):
        return self._only_one.locked() or self.busy()

    def kill_popen(self):
        if self.popen_work():
            self._popen.kill()
            self.log('Stop playing', logger.DEBUG)

    def quiet(self):
        if self.popen_work():
            self._lp_play.clear()

    def full_quiet(self):
        # Глушим все что можно
        self._lp_play.clear()
        self.kill_popen()

    def popen_work(self):
        return self._popen is not None and self._popen.poll() is None

    def _wait_popen(self, timeout=2):
        try:
            self._popen.wait(timeout)
        except subprocess.TimeoutExpired:
            self.kill_popen()

    def _no_background_play(self, lvl, blocking):
        if not self._cfg.gts('no_background_play'):
            return lvl, blocking
        return lvl if lvl >= 5 else 2, 250

    def play(self, file, lvl: int=2, wait=0, blocking: int=0):
        if not lvl and not self._cfg.gts('no_background_play'):
            self.log('low play \'{}\' pause {}'.format(file, wait), logger.DEBUG)
            return self._lp_play.play(file, wait)
        self._only_one.acquire()
        lvl, blocking = self._no_background_play(lvl, blocking)
        if not self.set_lvl(lvl):
            return

        time.sleep(0.01)
        self._play(file)
        if blocking:
            self._wait_popen(blocking)
        self._only_one.release()

        if wait:
            time.sleep(wait)

    def say_info(self, msg: str, lvl: int=2, alarm=None, wait=0, is_file: bool = False):
        if self._cfg.gts('quiet'):
            return
        self.say(msg, lvl, alarm, wait, is_file)

    def say(self, msg: str, lvl: int=2, alarm=None, wait=0, is_file: bool = False, blocking: int=0):
        if not lvl and not self._cfg.gts('no_background_play'):
            self.log('low say \'{}\' pause {}'.format(msg, wait), logger.DEBUG)
            return self._lp_play.say(msg, wait, is_file)
        self._only_one.acquire()
        lvl, blocking = self._no_background_play(lvl, blocking)
        if not self.set_lvl(lvl):
            return
        self.own.say_callback(True)
        if alarm is None:
            alarm = self._cfg.gts('alarmtts')

        file = self.own.tts(msg) if not is_file else msg

        time.sleep(0.01)
        if alarm:
            self._play(self._cfg.path['dong'])
            self._wait_popen()
        self._play(file, self.own.say_callback)
        if blocking:
            self._wait_popen(blocking)
        self._only_one.release()

        if wait:
            time.sleep(wait)

    def _play(self, obj, callback=None):
        if isinstance(obj, str):
            (path, stream, ext) = obj, None, None
        elif callable(obj):
            (path, stream, ext) = obj()
        elif isinstance(obj, (tuple, list)):
            (path, stream, ext) = obj
        else:
            raise RuntimeError('Get unknown object: {}'.format(str(obj)))
        self.kill_popen()
        ext = ext or os.path.splitext(path)[1]
        if not stream and not os.path.isfile(path):
            return self.log(LNG['file_not_found'].format(path), logger.ERROR)
        if ext not in linux_play.CMD:
            return self.log(LNG['unknown_type'].format(ext), logger.CRIT)
        if stream is None:
            self.log(LNG['play'].format(path, logger.DEBUG))
            self._popen = linux_play.get_popen(ext, path, False, callback)
        else:
            self.log(LNG['stream'].format(path, logger.DEBUG))
            self._popen = linux_play.get_popen(ext, stream, True, callback)


class LowPrioritySay(threading.Thread):
    def __init__(self, is_busy, say, play):
        super().__init__(name='LowPrioritySay')
        self._play = play
        self._say = say
        self._is_busy = is_busy
        self._queue_in = queue.Queue()
        self._work = False

    def start(self):
        self._work = True
        super().start()

    def stop(self):
        self._work = False
        self._queue_in.put_nowait(None)
        self.join()

    def clear(self):
        while not self._queue_in.empty():
            try:
                self._queue_in.get_nowait()
            except queue.Empty:
                pass

    def say(self, msg: str, wait: float or int=0, is_file: bool = False):
        self._put(1 if not is_file else 3, msg, wait)

    def play(self, file: str, wait: float or int=0):
        self._put(2, file, wait)

    def _put(self, action, target, wait):
        self._queue_in.put_nowait([action, target, wait])

    def run(self):
        while self._work:
            say = self._queue_in.get()
            while self._is_busy() and self._work:
                time.sleep(0.01)
            if say is None or not self._work:
                break
            if say[0] in [1, 3]:
                self._say(msg=say[1], lvl=1, wait=say[2], is_file=say[0] == 3)
            elif say[0] == 2:
                self._play(file=say[1], lvl=1, wait=say[2])



