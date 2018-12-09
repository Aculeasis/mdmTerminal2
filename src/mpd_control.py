#!/usr/bin/env python3

import threading
import time

import mpd

import logger
from languages import MPD_CONTROL as LNG
from owner import Owner


def _auto_reconnect(func):
    def wrapper(*args):
        try:
            return func(*args)
        except (mpd.MPDError, IOError):
            args[0].connect()
            if not args[0].is_conn:
                return None
            else:
                return func(*args)
    return wrapper


class MPDControl(threading.Thread):
    START_DELAY = 6

    def __init__(self, cfg: dict, log, owner: Owner):
        super().__init__(name='MPDControl')
        self._cfg = cfg  # ip, port, wait, quieter, control
        self.log = log
        self.own = owner
        self._work = False
        self._mpd = mpd.MPDClient(use_unicode=True)
        self.is_conn = False
        self._errors = 0
        self._reload = False
        self._lock = threading.Lock()

        self._old_volume = None
        self._resume = False
        self._be_resumed = False

        self._saved_volume = None
        self._saved_state = None

    def connect(self):
        if self.is_conn:
            self._disconnect()
        try:
            self._mpd.connect(self._cfg['ip'], self._cfg['port'])
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
            self._force_resume()
            self._work = False
            super().join(timeout)
            self.log('stop.', logger.INFO)

    def start(self):
        if self._cfg.get('control', 0):
            self._work = True
            super().start()

    def reload(self):
        self._reload = True

    def _init(self):
        time.sleep(self.START_DELAY)
        if not self.connect():
            self.own.say(LNG['err_mpd'], 0)
            return False
        self.log('start', logger.INFO)
        return True

    def play(self, uri):
        if not self.allow():
            return
        self._force_resume()
        self._mpd_add(uri)

    @property
    def plays(self):
        # MPD что-то играет
        return self.allow() and self._mpd_is_play()

    def pause(self, paused=None):
        if not self.allow():
            return
        if paused is None:
            self._force_resume()
            self._mpd_pause()
        elif paused:
            if self._mpd_is_play():
                self._start_paused()
        else:
            self._be_resumed = True

    def _start_paused(self):
        if not self._cfg['pause']:
            return
        with self._lock:
            self._resume = True
            self._be_resumed = False
            if 101 > self._cfg['quieter'] > 0:
                volume = self.volume
                if volume <= self._cfg['quieter']:
                    return
                if self._old_volume is None:
                    self._old_volume = volume
                self.volume = self._cfg['quieter']
            elif self._cfg['smoothly']:
                if self._old_volume is None:
                    self._old_volume = self.volume
                self._mpd_pause(True)
                self.volume = 0
            else:
                self._old_volume = None
                self._mpd_pause(True)

    def _stop_paused(self):
        if not self._cfg['pause']:
            return
        if self._mpd_get_state() == 'pause':
            self._mpd_pause(False)
        if self._cfg['smoothly']:
            self._smoothly_up()
        else:
            self._force_resume()

    def _force_resume(self):
        if not (self._resume and self._cfg['pause']):
            return
        with self._lock:
            self._resume = False
            self._be_resumed = False
            if self._old_volume is not None:
                self.volume = self._old_volume
                self._old_volume = None
            if self._mpd_get_state() == 'pause':
                self._mpd_pause(False)

    def _smoothly_up(self):
        # Медленно повышаем громкость
        if self._old_volume is None:
            self._force_resume()
        with self._lock:
            volume = self.volume
            inc = int((self._old_volume - volume) / 4)
            volume += inc if inc > 10 else 10
            if volume >= self._old_volume:
                volume = self._old_volume
                self._old_volume = None
                self._resume = False
                self._be_resumed = False
            self.volume = volume

    @property
    def real_volume(self):
        if not self.allow():
            return -1
        return self._old_volume or self._mpd_get_volume()

    @real_volume.setter
    def real_volume(self, vol):
        if not self.allow():
            return
        if self._old_volume is None:
            self._mpd_set_volume(vol)
        else:
            self._old_volume = vol

    @property
    def volume(self):
        if not self.allow():
            return -1
        return self._mpd_get_volume()

    @volume.setter
    def volume(self, vol):
        if not self.allow():
            return
        self._mpd_set_volume(vol)

    def run(self):
        if not self._init():
            self._work = False
        while self._work:
            time.sleep(0.9)
            self._resume_check()
            self._callbacks_event()
        self._disconnect()

    def _resume_check(self):
        if self._reload:
            self._reload = False
            self._force_resume()
            self.connect()
        if self._resume and self._be_resumed:
            self._stop_paused()

    def _callbacks_event(self):
        status = self._mpd_get_status()
        if not status:
            return
        if self._old_volume is None:
            volume = str_to_int(status.get('volume', -1))
            if volume != self._saved_volume:
                self.own.mpd_volume_callback(volume)
                self._saved_volume = volume
        state = status.get('state', 'stop')
        if state != self._saved_state:
            self.own.mpd_status_callback(state)
            self._saved_state = state

    @_auto_reconnect
    def _mpd_pause(self, pause=None):
        if pause is not None:
            self._mpd.pause(1 if pause else 0)
        else:
            self._mpd.pause()

    @_auto_reconnect
    def _mpd_add(self, uri):
        self._mpd.clear()
        self._mpd.add(uri)
        self._mpd.play(0)

    @_auto_reconnect
    def _mpd_set_volume(self, vol):
        return self._mpd.setvol(vol)

    @_auto_reconnect
    def _mpd_get_volume(self):
        return str_to_int(self._mpd.status().get('volume', -1))

    def _mpd_is_play(self) -> bool:
        return self._mpd_get_state() == 'play'

    @_auto_reconnect
    def _mpd_get_state(self):
        return self._mpd.status().get('state', 'stop')

    @_auto_reconnect
    def _mpd_get_status(self) -> dict:
        return self._mpd.status()


def str_to_int(val: str) -> int or None:
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
