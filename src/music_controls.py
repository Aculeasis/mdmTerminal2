#!/usr/bin/env python3

import threading

try:
    # FIX: ValueError: signal only works in main thread
    import socketio
except ImportError as _e:
    class socketio:
        e = _e

        @classmethod
        def Client(cls, *_, **__):
            raise ImportError(cls.e)

import logger as logger_
from lib.base_music_controller import str_to_int, BaseControl, auto_reconnect
from owner import Owner
from utils import get_ip_address, url_builder_cached
from lib.dlna.dlna import find_MediaRenderer
from lib.dlna import media_render


class DummyControl:
    name = 'DummyControl'
    work = False
    plays = False
    get_track_name = None
    is_conn = False

    def __init__(self, *_, **__):
        pass

    def start(self):
        pass

    def join(self, timeout=None):
        pass

    def pause(self, paused=None):
        pass

    def reload(self):
        pass

    def play(self, uri):
        pass

    @staticmethod
    def allow():
        return False

    @staticmethod
    def state() -> str:
        return 'disabled'

    volume = property(lambda self: -1, play)
    real_volume = volume


class MPDControl(BaseControl):
    def __init__(self, name, cfg: dict, log, owner: Owner):
        super().__init__(name, cfg, log, owner)
        import mpd
        self.__lib = mpd
        self._mpd = self.__lib.MPDClient(use_unicode=True)

    def reconnect_wrapper(self, func, *args):
        try:
            return func(*args)
        except (self.__lib.MPDError, IOError):
            self._connect()
            if not self.is_conn:
                return None
            else:
                return func(*args)

    def _connect(self):
        if self.is_conn:
            self._disconnect()
        self.is_conn = False
        if not self._cfg['control']:
            return False
        try:
            self._mpd.connect(self._cfg['ip'], self._cfg['port'], 15)
        except (self.__lib.MPDError, IOError) as e:
            return self._is_connect_error(e)
        else:
            self.is_conn = True
            return True

    def _disconnect(self):
        self.is_conn = False
        try:
            self._mpd.close()
        except (self.__lib.MPDError, IOError):
            pass
        try:
            self._mpd.disconnect()
        except (self.__lib.MPDError, IOError):
            self._mpd = self.__lib.MPDClient(use_unicode=True)

    @auto_reconnect
    def _ctl_pause(self, pause=None):
        if pause is not None:
            self._mpd.pause(1 if pause else 0)
        else:
            self._mpd.pause()

    @auto_reconnect
    def _ctl_add(self, uri):
        self._mpd.clear()
        self._mpd.add(uri)
        self._mpd.play(0)

    @auto_reconnect
    def _ctl_set_volume(self, vol):
        return self._mpd.setvol(vol)

    @auto_reconnect
    def _ctl_get_volume(self):
        return str_to_int(self._mpd.status().get('volume', -1))

    def _ctl_is_play(self) -> bool:
        return self._ctl_get_state() == 'play'

    @auto_reconnect
    def _ctl_get_state(self):
        return self._mpd.status().get('state', 'stop')

    @auto_reconnect
    def _ctl_get_status(self) -> dict:
        return self._mpd.status()

    @auto_reconnect
    def _ctl_get_track_name(self):
        song = self._mpd.currentsong()
        try:
            return '{title} from {artist}'.format(**song)
        except (KeyError, TypeError):
            pass


class LMSControl(BaseControl):
    def __init__(self, name, cfg: dict, log, owner: Owner):
        super().__init__(name, cfg, log, owner)
        from pylms.server import Server as LMSServer  # install git+https://github.com/Aculeasis/PyLMS.git
        self.__lib = LMSServer
        self._lms = self.__lib()
        self._player = None
        self._lock = threading.Lock()

    def reconnect_wrapper(self, func, *args):
        try:
            with self._lock:
                return func(*args)
        except (AttributeError, IOError, EOFError, ValueError):
            self._connect()
            if not self.is_conn:
                return None
            else:
                with self._lock:
                    return func(*args)

    def _connect(self):
        if self.is_conn:
            self._disconnect()
        self.is_conn = False
        if not self._cfg['control']:
            return False
        self._lms = self.__lib(self._cfg['ip'], self._cfg['port'], self._cfg['username'], self._cfg['password'])
        try:
            try:
                self._lms.connect()
            except EOFError as e:
                raise RuntimeError('Login failed?: {}'.format(e))
            self._player = self._lms_get_one_player(self._cfg['lms_player'], self._lms.get_players())
        except (IOError, RuntimeError, ValueError) as e:
            self._player = None
            return self._is_connect_error(e)
        else:
            self.log('Linked to {} on {}'.format(self._player.name, self._player.ip_address), logger_.INFO)
            self.is_conn = True
            return True

    def _disconnect(self):
        self.is_conn = False
        try:
            self._lms.disconnect()
        except (AttributeError, IOError, EOFError, ValueError):
            pass
        self._lms = self.__lib()

    @auto_reconnect
    def _ctl_pause(self, pause=None):
        if pause is not None:
            if pause:
                self._player.pause()
            else:
                self._player.unpause()
        else:
            self._player.toggle()

    @auto_reconnect
    def _ctl_add(self, uri):
        self._player.playlist_play(uri)

    @auto_reconnect
    def _ctl_set_volume(self, vol):
        self._player.set_volume(vol)

    @auto_reconnect
    def _ctl_get_volume(self):
        return self._player.get_volume()

    def _ctl_is_play(self) -> bool:
        return self._ctl_get_state() == 'play'

    @auto_reconnect
    def _ctl_get_state(self):
        return self._player.get_mode() or 'stop'

    def _ctl_get_status(self) -> dict:
        return {'state': self._ctl_get_state(), 'volume': self._ctl_get_volume()}

    @auto_reconnect
    def _ctl_get_track_name(self) -> str or None:
        return self._player.get_track_title()

    @staticmethod
    def _lms_player_match(player, uid: str) -> bool:
        if player.name == uid or player.ref == uid or player.ip_address.split(':', 1)[0] == uid:
            return True
        return False

    def _lms_get_one_player(self, uid: str, players):
        ip = get_ip_address()
        first, my_ip = None, None
        for player in players:
            if uid and self._lms_player_match(player, uid):
                return player
            if my_ip is None and player.ip_address.split(':', 1)[0] == ip:
                my_ip = player
            if first is None:
                first = player
        my_ip = my_ip or first
        if not my_ip:
            raise RuntimeError('No players found')
        return my_ip


class Volumio2Control(BaseControl):
    ERROR_STATUS = {'state': 'null', 'title': 'null', 'artist': 'null', 'volume': -1}

    def __init__(self, name, cfg: dict, log, owner: Owner):
        super().__init__(name, cfg, log, owner)
        self._status = self.ERROR_STATUS
        self._status_wait = threading.Event()

        self._ws = socketio.Client(reconnection=False)
        self._ws.on('pushState', self._event_status)
        self._ws.on('connect', self._event_connect)
        self._ws.on('disconnect', self._event_disconnect)

    def _event_status(self, data):
        data['state'] = data['status']
        self._status = data
        self._status_wait.set()

    def _event_disconnect(self, *_):
        self._status = self.ERROR_STATUS
        self.is_conn = False
        self._status_wait.set()

    def _event_connect(self, *_):
        self.is_conn = True
        self._status_wait.set()

    def reconnect_wrapper(self, func, *args):
        try:
            return func(*args)
        except socketio.client.exceptions.SocketIOError:
            self._connect()
            if not self.is_conn:
                return None
            else:
                return func(*args)

    def _connect(self):
        if self.is_conn:
            self._disconnect()
        if not self._cfg['control']:
            return False
        self._status_wait.clear()
        try:
            self._ws.connect(url_builder_cached(self._cfg['ip'], def_port=self._cfg['port']))
            self._status_wait.wait(0.5)
            self._status_wait.clear()
            self._ws.emit('getStatus')
            self._status_wait.wait(0.2)
        except socketio.client.exceptions.SocketIOError as e:
            return self._is_connect_error(e)
        return self.is_conn

    def _disconnect(self):
        self._status_wait.clear()
        try:
            self._ws.disconnect()
            self._status_wait.wait(1)
        except socketio.client.exceptions.SocketIOError:
            pass

    @auto_reconnect
    def _ctl_pause(self, pause=None):
        is_play = self._ctl_is_play()
        if pause is None:
            self._ws.emit('pause' if is_play else 'play')
        else:
            if is_play == pause:
                self._status_wait.clear()
            self._ws.emit('pause' if pause else 'play')
            if is_play == pause:
                self._status_wait.wait(0.1)

    @auto_reconnect
    def _ctl_add(self, uri):
        # FIXME: This won't work
        pass

    @auto_reconnect
    def _ctl_set_volume(self, vol):
        wait = vol != self._ctl_get_volume()
        if wait:
            self._status_wait.clear()
        self._ws.emit('volume', vol)
        if wait:
            self._status_wait.wait(0.1)
        return self._ctl_get_volume()

    def _ctl_get_volume(self):
        return str_to_int(self._status.get('volume', -1))

    def _ctl_is_play(self) -> bool:
        return self._ctl_get_state() == 'play'

    def _ctl_get_state(self) -> str:
        return self._status.get('state', 'stop')

    def _ctl_get_status(self) -> dict:
        return self._status

    def _ctl_get_track_name(self):
        try:
            return '{title} from {artist}'.format(**self._status)
        except (KeyError, TypeError):
            return 'error'


class DLNAControl(BaseControl):
    def __init__(self, name, cfg: dict, log, owner: Owner):
        super().__init__(name, cfg, log, owner)
        self._dlna = media_render.MediaRender({})

    def reconnect_wrapper(self, func, *args):
        try:
            return func(*args)
        except media_render.Error:
            self._connect()
            if not self.is_conn:
                return None
            else:
                return func(*args)

    def _connect(self):
        if self.is_conn:
            self._disconnect()
        self.is_conn = False
        if not self._cfg['control']:
            return False
        try:
            self._dlna = find_MediaRenderer(self._cfg['ip'], self._cfg['ip'])
        except media_render.Error as e:
            return self._is_connect_error(e)
        else:
            self.log('Connected to {}'.format(self._dlna.pretty_name), logger_.INFO)
            self._dlna.log_cb = lambda x: self.log(x, logger_.WARN)
            self.is_conn = True
            return True

    def _disconnect(self):
        self.is_conn = False
        self._dlna.broken = True

    @auto_reconnect
    def _ctl_pause(self, pause=None):
        self._dlna.pause(pause)

    @auto_reconnect
    def _ctl_add(self, uri):
        self._dlna.play(uri)

    @auto_reconnect
    def _ctl_set_volume(self, vol):
        self._dlna.volume = vol

    @auto_reconnect
    def _ctl_get_volume(self):
        return str_to_int(self._dlna.volume)

    def _ctl_is_play(self) -> bool:
        return self._ctl_get_state() == 'play'

    @auto_reconnect
    def _ctl_get_state(self):
        return self._dlna.state()

    def _ctl_get_status(self) -> dict:
        return {'state': self._ctl_get_state(),  'volume': self._ctl_get_volume()}

    @auto_reconnect
    def _ctl_get_track_name(self):
        song = self._dlna.currentsong()
        try:
            return '{title} from {artist}'.format(**song)
        except (KeyError, TypeError):
            pass


TYPE_MAP = {
    'mpd': MPDControl,
    'lms': LMSControl,
    'volumio2': Volumio2Control,
    'dlna': DLNAControl
}


def music_constructor(cfg, logger, owner: Owner, old=None):
    def create():
        if name not in TYPE_MAP:
            cls = DummyControl
            owner.log('Wrong type of player controller - \'{}\''.format(name), logger_.ERROR)
        else:
            cls = TYPE_MAP[name]
        log = logger.add(name.upper())
        try:
            return cls(name, cfg['music'], log, owner)
        except Exception as e:
            log('Init Error: {}'.format(e), logger_.CRIT)
            return DummyControl()

    if not (old is None or isinstance(old, (BaseControl, DummyControl))):
        raise TypeError('Wrong type: {}'.format(type(old)))

    name = cfg.gt('music', 'type', '').lower()
    if old:
        if old.name == name:
            old.reload()
            return old
        else:
            owner.join_thread(old)
            old = create()
            old.start()
    else:
        old = create()
    return old
