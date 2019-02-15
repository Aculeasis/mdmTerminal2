#!/usr/bin/env python3

import mpd
from pylms.server import Server as LMSServer  # install git+https://github.com/Aculeasis/PyLMS.git

import logger as logger_
from languages import MUSIC_CONTROL as LNG
from lib.base_music_controller import str_to_int, BaseControl, auto_reconnect
from owner import Owner
from utils import get_ip_address


class MPDControl(BaseControl):
    def __init__(self, name, cfg: dict, log, owner: Owner):
        super().__init__(name, cfg, log, owner)
        self._mpd = mpd.MPDClient(use_unicode=True)

    def reconnect_wrapper(self, func, *args):
        try:
            return func(*args)
        except (mpd.MPDError, IOError):
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
        except (mpd.MPDError, IOError) as e:
            msg = LNG['err_conn'].format(self._name.upper())
            self.log('{}: {}'.format(msg, e), logger_.ERROR)
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


class LMSControl(BaseControl):
    def __init__(self, name, cfg: dict, log, owner: Owner):
        super().__init__(name, cfg, log, owner)
        self._lms = LMSServer()
        self._player = None

    def reconnect_wrapper(self, func, *args):
        try:
            return func(*args)
        except (AttributeError, IOError, EOFError, ValueError):
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
        self._lms = LMSServer(self._cfg['ip'], self._cfg['port'], self._cfg['username'], self._cfg['password'])
        try:
            try:
                self._lms.connect()
            except EOFError as e:
                raise RuntimeError('Login failed?: {}'.format(e))
            self._player = self._lms_get_one_player(self._cfg['lms_player'], self._lms.get_players())
        except (IOError, RuntimeError, ValueError) as e:
            msg = LNG['err_conn'].format(self._name.upper())
            self.log('{}: {}'.format(msg, e), logger_.ERROR)
            self.is_conn = False
            self._player = None
            return False
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
        self._lms = LMSServer()

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


TYPE_MAP = {
    'mpd': MPDControl,
    'lms': LMSControl,
}


def music_constructor(cfg, logger, owner: Owner, old=None) -> BaseControl:
    if not (old is None or isinstance(old, BaseControl)):
        raise TypeError('Wrong type: {}'.format(type(old)))

    name = cfg.gt('music', 'type', '').lower()
    if name not in TYPE_MAP:
        name = 'mpd'
    if old:
        if old.name == name:
            old.reload()
            return old
        else:
            old.join(20)
            old = TYPE_MAP[name](name, cfg['music'], logger.add(name.upper()), owner)
            old.start()
    else:
        old = TYPE_MAP[name](name, cfg['music'], logger.add(name.upper()), owner)
    return old
