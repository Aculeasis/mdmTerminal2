#!/usr/bin/env python3

import queue
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
    MAX_ERRORS = 5

    def __init__(self, cfg: dict, log, owner: Owner):
        super().__init__(name='MPDControl')
        self._cfg = cfg  # ip, port, wait, quieter, control
        self.log = log
        self.own = owner
        self._work = False
        self._mpd = mpd.MPDClient(use_unicode=True)
        self.is_conn = False
        self._errors_metric = 0
        self._queue = queue.Queue()

        self._old_volume = None
        self._resume = False
        self._be_resumed = False
        self._is_auto_paused = False
        self._resume_time = None
        self._previus_volume = None
        self._check_un_pause = False

        self._saved_volume = None
        self._saved_state = None

        # Состояния для автопаузы
        self._pause_flags = {
            'start_record': 0b100,
            'stop_record': 0b100,
            'start_talking': 0b010,
            'stop_talking': 0b010,
            'start_stt_event': 0b001,
            'stop_stt_event': 0b001,
        }
        # Состояние автопаузы
        self._pause_flag = 0b000
        self._events = (
            (('start_record', 'start_talking', 'start_stt_event', 'voice_activated'), self._cb_pause),
            (('stop_record', 'stop_talking', 'stop_stt_event'), self._cb_unpause)
        )

    def _subscribe(self):
        if self._cfg['pause'] and self._cfg['control']:
            for events, callback in self._events:
                self.own.subscribe(events, callback)

    def _unsubscribe(self):
        for events, callback in self._events:
            self.own.unsubscribe(events, callback)

    def _cb_unpause(self, name, *_, **__):
        if name in self._pause_flags:
            self._pause_flag ^= self._pause_flags[name]
        if not self._pause_flag:
            self.pause(False)

    def _cb_pause(self, name, *_, **__):
        self.pause(True)
        if name in self._pause_flags:
            self._pause_flag |= self._pause_flags[name]

    def connect(self):
        if self.is_conn:
            self._disconnect()
        self.is_conn = False
        if not self._cfg['control']:
            return False
        try:
            self._mpd.connect(self._cfg['ip'], self._cfg['port'])
        except (mpd.MPDError, IOError) as e:
            self.log('{}: {}'.format(LNG['err_mpd'], e), logger.ERROR)
            self.is_conn = False
            return False
        else:
            self.is_conn = True
            return True

    def _disconnect(self):
        self.is_conn = False
        try:
            self._mpd.close()
        except (mpd.MPDError, IOError):
            pass
        try:
            self._mpd.disconnect()
        except (mpd.MPDError, IOError):
            self._mpd = mpd.MPDClient(use_unicode=True)

    def allow(self):
        return self.is_conn and self._work

    def join(self, timeout=None):
        if self._work:
            self._work = False
            self._queue.put_nowait(None)
            self.log('stopping...', logger.DEBUG)
            super().join(timeout)
            self.log('stop.', logger.INFO)

    def start(self):
        if not self._work:
            self._work = True
            super().start()

    def reload(self):
        if self._work:
            self._queue.put_nowait(('reload', None))

    def _init(self):
        if self._cfg['control']:
            time.sleep(self.START_DELAY)
            if not self.connect():
                self.own.say(LNG['err_mpd'], 0)
        self.log('start', logger.INFO)

    def play(self, uri):
        if not self.allow():
            return
        self._queue.put_nowait(('play', uri))

    def _play(self, uri):
        self._force_resume()
        self._mpd_add(uri)

    @property
    def plays(self):
        # MPD что-то играет
        return self.allow() and self._mpd_is_play()

    def pause(self, paused=None):
        if not self.allow():
            return
        if paused is None or self._cfg['pause']:
            self._queue.put_nowait(('pause', paused))

    def _pause(self, paused=False):
        if paused is None:
            self._force_resume()
            self._mpd_pause()
        elif paused:
            self._is_auto_paused = self._is_auto_paused or self._mpd_is_play()
            if self._is_auto_paused:
                self._start_paused()
        else:
            self._be_resumed = True

    def _start_paused(self):
        self._resume = True
        self._be_resumed = False
        self._resume_time = None
        self._previus_volume = None
        if 101 > self._cfg['quieter'] > 0:
            volume = self.volume
            if volume <= self._cfg['quieter']:
                return
            if self._old_volume is None:
                self._old_volume = volume
            self.volume, self._previus_volume = self._cfg['quieter'], self._cfg['quieter']
            self._check_un_pause = False
        elif self._cfg['smoothly']:
            if self._old_volume is None:
                self._old_volume = self.volume
            self.volume, self._previus_volume = 0, 0
            self._check_un_pause = True
            self._mpd_pause(True)
        else:
            self._old_volume = None
            self._check_un_pause = True
            self._mpd_pause(True)

    def _stop_paused(self):
        is_paused = self._mpd_get_state() == 'pause'
        if is_paused == self._check_un_pause:
            if self._check_un_pause:
                self._check_un_pause = False
                self._mpd_pause(False)
        else:
            return self._stop_resume()
        if self._cfg['smoothly']:
            self._smoothly_up()
        else:
            self._force_resume()

    def _force_resume(self, always=False):
        if not (self.allow() or always) and self._resume:
            return

        self._resume = False
        self._be_resumed = False
        if not self._is_auto_paused:
            self._old_volume = None
            return
        self._is_auto_paused = False
        if self._old_volume is not None:
            self._mpd_set_volume(self._old_volume)
            self._old_volume = None
        if self._mpd_get_state() == 'pause':
            self._mpd_pause(False)

    def _stop_resume(self):
        # Что-то пошло не так
        self._old_volume = None
        self._resume = False
        self._be_resumed = False
        self._is_auto_paused = False

    def _smoothly_up(self):
        # Медленно повышаем громкость
        if self._old_volume is None:
            return self._force_resume()

        volume = self.volume
        if volume != self._previus_volume:
            return self._stop_resume()
        inc = int((self._old_volume - volume) / 4)
        volume += inc if inc > 10 else 10
        if volume >= self._old_volume:
            self._force_resume()
        else:
            self.volume, self._previus_volume = volume, volume

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
        self._init()
        self._subscribe()
        while self._work:
            try:
                cmd = self._queue.get(timeout=0.9)
            except queue.Empty:
                pass
            else:
                if cmd is None:
                    break
                elif cmd[0] == 'pause':
                    self._pause(cmd[1])
                elif cmd[0] == 'play':
                    self._play(cmd[1])
                elif cmd[0] == 'reload':
                    self._errors_metric = 0
                    self._unsubscribe()
                    self._force_resume(True)
                    self.connect()
                    self._subscribe()
                    continue
            if self.is_conn:
                self._resume_check()
                self._callbacks_event()
            elif self._cfg['control'] and self._errors_metric >= 0:
                self._errors_metric += 1
                if not self._errors_metric % 10:
                    if self.connect():
                        self._errors_metric = 0
                if self._errors_metric >= (self.MAX_ERRORS * 10) - 10:
                    self.log('Detected many errors [{}] - stop reconnecting.'.format(self.MAX_ERRORS), logger.CRIT)
                    self._errors_metric = -1
        self._unsubscribe()
        self._force_resume(True)
        self._disconnect()

    def _resume_check(self):
        if self._resume and self._be_resumed:
            if not self._resume_time and self._cfg['wait_resume'] > 0:
                self._resume_time = time.time() + self._cfg['wait_resume']
            if self._resume_time and time.time() < self._resume_time:
                return
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
