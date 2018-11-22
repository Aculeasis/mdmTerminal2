#!/usr/bin/env python3

import threading
import time

import mpd

import logger
from languages import MPD_CONTROL as LNG


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


class MPDControl(threading.Thread):
    START_DELAY = 6

    def __init__(self, cfg: dict, log, play):
        super().__init__(name='MPDControl')
        self.IP = cfg.get('ip', '127.0.0.1')
        self.PORT = cfg.get('port', 6600)
        self.RESUME_TIME = cfg.get('wait', 13)

        self._last_play = play.last_activity
        self._say = play.say
        self.log = log
        self._work = False
        self._mpd = mpd.MPDClient(use_unicode=True)
        self._resume = False
        self.is_conn = False
        self._errors = 0

    def connect(self):
        if self.is_conn:
            self._disconnect()
        try:
            self._mpd.connect(self.IP, self.PORT)
        except (mpd.MPDError, IOError) as e:
            self.log('{}: {}'.format(LNG['err_mpd'], e), logger.ERROR)
            self.is_conn = False
            self._errors += 1
            if self._errors > 5:
                self.log('Detected many error - stopping.', logger.CRIT)
                self._work = False
            return False
        else:
            self.is_conn = True
            self._errors = 0
            return True

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

    def join(self, timeout=None):
        if self._work:
            self.log('stopping...', logger.DEBUG)
            self._resume_check()
            self._work = False
            super().join(timeout)
            self.log('stop.', logger.INFO)

    def start(self):
        self._work = True
        super().start()

    def _init(self):
        time.sleep(self.START_DELAY)
        if not self.connect():
            self._say(LNG['err_mpd'], 0)
            return False
        self.log('start', logger.INFO)
        return True

    def play(self, uri):
        if not self.allow():
            return
        self._mpd_add(uri)
        self._resume = False

    @property
    def plays(self):
        # MPD что-то играет
        return self.allow() and self._mpd_is_play()

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

    def run(self):
        ping = 0
        if not self._init():
            self._work = False
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
