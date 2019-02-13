#!/usr/bin/env python3

import mpd

import logger as logger_
from languages import MUSIC_CONTROL as LNG
from lib.base_music_controller import str_to_int, BaseControl, auto_reconnect
from owner import Owner


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
            self._mpd.connect(self._cfg['ip'], self._cfg['port'])
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


TYPE_MAP = {
    'mpd': MPDControl,
}


def music_constructor(cfg, logger, owner: Owner, old=None) -> BaseControl:
    # TODO: mpd -> music
    if not (old is None or isinstance(old, BaseControl)):
        raise TypeError('Wrong type: {}'.format(type(old)))

    name = cfg.gt('mpd', 'type', '').lower()
    if name not in TYPE_MAP:
        name = 'mpd'
    if old:
        if old.name == name:
            old.reload()
            return old
        else:
            old.join(20)
            old = TYPE_MAP[name](name, cfg['mpd'], logger.add(name.upper()), owner)
            old.start()
    else:
        old = TYPE_MAP[name](name, cfg['mpd'], logger.add(name.upper()), owner)
    return old
