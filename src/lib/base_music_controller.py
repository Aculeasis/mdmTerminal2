import queue
import threading
import time

import logger
from languages import MUSIC_CONTROL as LNG
from owner import Owner
from utils import str_to_list

__all__ = ['str_to_int', 'BaseControl', 'auto_reconnect']

PAUSE_STATES = {
    'start_record': 0b100,
    'stop_record': 0b100,
    'start_talking': 0b010,
    'stop_talking': 0b010,
    'start_stt_event': 0b001,
    'stop_stt_event': 0b001,
}
EVENTS = (
    ('start_record', 'start_talking', 'start_stt_event', 'voice_activated'),  # pause
    ('stop_record', 'stop_talking', 'stop_stt_event')  # unpause
)


def auto_reconnect(func):
    def wrapper(*args):
        return args[0].reconnect_wrapper(func, *args)
    return wrapper


def str_to_int(val: str) -> int or None:
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


class BaseControl(threading.Thread):
    START_DELAY = 6
    MAX_ERRORS = 6
    CHECK_INTERVAL = 0.9
    # Расчетное время переподключения. Реальное будет плавать.
    BASE_RECONN_TIME = 20

    def __init__(self, name: str, cfg: dict, log, owner: Owner):
        super().__init__(name='{}Control'.format(name.upper()))
        self._name = name
        self._cfg = cfg  # ip, port, wait, quieter, control, etc.
        self.log = log
        self.own = owner
        self.work = False

        self.is_conn = False
        self._errors_metric = 0
        self._errors_rate = max(int(self.BASE_RECONN_TIME/self.CHECK_INTERVAL), 1)
        self._queue = queue.Queue()

        self._check_time = self.CHECK_INTERVAL
        self._old_volume = None
        self._resume = False
        self._be_resumed = False
        self._is_auto_paused = False
        self._resume_time = None
        self._previus_volume = None
        self._check_un_pause = False
        self._starting_unpause_volume = None

        self._saved_volume = None
        self._saved_state = None

        self._pause_state = 0b000
        self._events = self._make_events()

    def _make_events(self) -> tuple:
        ignore = set(str_to_list(self._cfg['ignore_events']))

        def make(data: tuple) -> tuple:
            return tuple(x for x in data if x not in ignore)

        return (make(EVENTS[0]), self._cb_pause), (make(EVENTS[1]), self._cb_unpause)

    def _subscribe(self):
        if self._cfg['pause'] and self._cfg['control']:
            self._events = self._make_events()
            for events, callback in self._events:
                self.own.subscribe(events, callback)

    def _unsubscribe(self):
        for events, callback in self._events:
            self.own.unsubscribe(events, callback)

    def _cb_unpause(self, name, *_, **__):
        if name in PAUSE_STATES:
            self._pause_state ^= PAUSE_STATES[name]
        if not self._pause_state:
            self.pause(False)

    def _cb_pause(self, name, *_, **__):
        self.pause(True)
        if name in PAUSE_STATES:
            self._pause_state |= PAUSE_STATES[name]

    @property
    def name(self) -> str:
        return self._name

    def reconnect_wrapper(self, func, *args):
        raise NotImplementedError

    def _connect(self):
        raise NotImplementedError

    def _disconnect(self):
        raise NotImplementedError

    def allow(self):
        return self.is_conn and self.work

    def join(self, timeout=30):
        self._queue.put_nowait(None)
        super().join(timeout=timeout)

    def start(self):
        if not self.work:
            self.work = True
            super().start()

    def _reload(self):
        self._errors_metric = 0
        self._unsubscribe()
        self._force_resume(True)
        self._connect()
        self._subscribe()

    def reload(self):
        if self.work:
            self._queue.put_nowait(('reload', None))

    def _init(self):
        if self._cfg['control']:
            time.sleep(self.START_DELAY)
            if not self._connect():
                self.own.say(LNG['err_conn'].format(self._name.upper()), 0)
        self.log('start', logger.INFO)

    def get_track_name(self) -> str or None:
        if self.allow():
            return self._ctl_get_track_name()

    def play(self, uri):
        if not self.allow():
            return
        self._queue.put_nowait(('play', uri))

    def _play(self, uri):
        self._force_resume()
        self._ctl_add(uri)

    @property
    def plays(self):
        # что-то играет
        return self.allow() and self._ctl_is_play()

    def pause(self, paused=None):
        if not self.allow():
            return
        if paused is None or self._cfg['pause']:
            self._queue.put_nowait(('pause', paused))

    def _pause(self, paused=False):
        if paused is None:
            self._force_resume()
            self._ctl_pause()
        elif paused:
            self._is_auto_paused = self._is_auto_paused or self._ctl_is_play()
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
            self._starting_unpause_volume = 0
            self._check_un_pause = True
            self._ctl_pause(True)
        else:
            self._old_volume = None
            self._check_time = self.CHECK_INTERVAL
            self._check_un_pause = True
            self._ctl_pause(True)

    def _stop_paused(self):
        is_paused = self._ctl_get_state() == 'pause'
        if is_paused == self._check_un_pause:
            if self._check_un_pause:
                self._check_un_pause = False
                if self._starting_unpause_volume is not None:
                    self.volume = self._starting_unpause_volume
                    self._starting_unpause_volume = None
                    self._previus_volume = self.volume
                self._ctl_pause(False)
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
        self._starting_unpause_volume = None
        if not self._is_auto_paused:
            self._old_volume = None
            self._check_time = self.CHECK_INTERVAL
            return
        self._is_auto_paused = False
        if self._old_volume is not None:
            self._ctl_set_volume(self._old_volume)
            self._old_volume = None
            self._check_time = self.CHECK_INTERVAL
        if self._ctl_get_state() == 'pause':
            self._ctl_pause(False)

    def _stop_resume(self):
        # Что-то пошло не так
        self._starting_unpause_volume = None
        self._old_volume = None
        self._check_time = self.CHECK_INTERVAL
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
        inc = int((self._old_volume - volume) / 10)
        volume += inc if inc > 5 else 5
        if volume >= self._old_volume:
            self._force_resume()
        else:
            self._check_time = 0.2
            self.volume, self._previus_volume = volume, volume

    @property
    def real_volume(self):
        if not self.allow():
            return -1
        return self._old_volume or self._ctl_get_volume()

    @real_volume.setter
    def real_volume(self, vol):
        if not self.allow():
            return
        if self._old_volume is None:
            self._ctl_set_volume(vol)
        else:
            self._old_volume = vol

    @property
    def volume(self):
        if not self.allow():
            return -1
        return self._ctl_get_volume()

    @volume.setter
    def volume(self, vol):
        if not self.allow():
            return
        self._ctl_set_volume(vol)

    def run(self):
        self._init()
        self._subscribe()
        while self.work:
            try:
                cmd = self._queue.get(timeout=self._check_time)
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
                    self._reload()
                    continue
            if self.is_conn:
                self._resume_check()
                self._callbacks_event()
            elif self._cfg['control'] and self._errors_metric >= 0:
                self._errors_metric += 1
                if not self._errors_metric % self._errors_rate and self._connect():
                    self._errors_metric = 0
                if self._errors_metric // self._errors_rate + 1 >= self.MAX_ERRORS:
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
        status = self._ctl_get_status()
        if not status:
            return
        if self._old_volume is None:
            volume = str_to_int(status.get('volume', -1))
            if volume != self._saved_volume:
                self.own.music_volume_callback(volume)
                self._saved_volume = volume
        state = status.get('state', 'stop')
        if state != self._saved_state:
            self.own.music_status_callback(state)
            self._saved_state = state

    @auto_reconnect
    def _ctl_pause(self, pause=None):
        raise NotImplemented

    @auto_reconnect
    def _ctl_add(self, uri):
        raise NotImplementedError

    @auto_reconnect
    def _ctl_set_volume(self, vol):
        raise NotImplementedError

    @auto_reconnect
    def _ctl_get_volume(self):
        raise NotImplementedError

    def _ctl_is_play(self) -> bool:
        raise NotImplementedError

    @auto_reconnect
    def _ctl_get_state(self):
        raise NotImplementedError

    @auto_reconnect
    def _ctl_get_status(self) -> dict:
        raise NotImplementedError

    @auto_reconnect
    def _ctl_get_track_name(self) -> str or None:
        raise NotImplementedError
