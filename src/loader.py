#!/usr/bin/env python3

import threading

import stts
from config import ConfigHandler
from languages import LOADER as LNG
from lib.proxy import proxies
from logger import Logger
from modules_manager import ModuleManager
from mpd_control import MPDControl
from player import Player
from server import MDTServer
from terminal import MDTerminal
from updater import Updater


class Loader:
    def __init__(self, init_cfg: dict, path: dict, die_in):
        self._die_in = die_in
        self.reload = False
        self._lock = threading.Lock()

        self._cfg = ConfigHandler(cfg=init_cfg, path=path)
        self._logger = Logger(self._cfg['log'])
        self._cfg.configure(self._logger.add('CFG'))

        proxies.add_logger(self._logger.add('Proxy'))

        self._tts = stts.TextToSpeech(cfg=self._cfg, log=self._logger.add('TTS')).tts

        self._play = Player(cfg=self._cfg, log=self._logger.add('Player'), tts=self._tts)

        self._mpd = MPDControl(cfg=self._cfg['mpd'], log=self._logger.add('MPD'), play=self._play)

        self._stt = stts.SpeechToText(cfg=self._cfg, play_=self._play, log=self._logger.add('STT'), tts=self._tts)

        self._mm = ModuleManager(
            log=self._logger.add_plus('MM'), cfg=self._cfg, die_in=self.die_in, say=self._play.say,
            terminal_call=self.call_terminal_call
        )

        self._updater = Updater(
            cfg=self._cfg, log=self._logger.add('Updater'), terminal_call=self.call_terminal_call, die_in=self.die_in
        )

        self._terminal = MDTerminal(
            cfg=self._cfg, play_=self._play, stt=self._stt,
            log=self._logger.add('Terminal'), handler=self._mm.tester, updater=self._updater
        )

        self._server = MDTServer(
            cfg=self._cfg, log=self._logger.add('Server'),  play=self._play,
            terminal_call=self.call_terminal_call, die_in=self.die_in, parse_settings=self.settings_from_mjd
        )

    def start(self):
        if self._cfg['mpd'].get('control', 0):
            self._mpd.start()
        self._play.start(self._mpd)
        self._play.say_info(LNG['hello'], 0, wait=0.5)
        self._stt.start()
        self._cfg.add_play(self._play)
        self._mm.start()
        self._updater.start()
        self._terminal.start()
        self._server.start()

    def stop(self):
        self._mm.save()
        self._server.join()
        self._terminal.join()
        self._updater.join()

        self._play.quiet()
        self._play.kill_popen()
        self._play.say_info(LNG['bye'])

        self._stt.stop()
        self._play.stop()
        self._mpd.join()
        self._logger.join()

    def die_in(self, wait, reload=False):
        self.reload = reload
        self._die_in(wait)

    def call_terminal_call(self, cmd: str, data='', lvl: int=0, save_time: bool=True):
        self._terminal.call(cmd, data, lvl, save_time)

    def settings_from_mjd(self, cfg: str):
        # Reload modules if their settings could be changes
        with self._lock:
            diff = self._cfg.update_from_json(cfg)
            if diff is None:
                self._cfg.print_cfg_no_change()
                return
            if is_sub_dict('settings', diff) and ('lang' in diff['settings'] or 'lang_check' in diff['settings']):
                # re-init lang
                lang = diff['settings'].pop('lang', None)
                diff['settings'].pop('lang_check', None)
                self._cfg.lang_init()
                if lang:
                    # change unsupported speakers to default
                    self._cfg.fix_speakers()
                    # reload modules
                    self._mm.reload()
            if is_sub_dict('log', diff):
                # reload logger
                self._logger.reload()
            if is_sub_dict('cache', diff):
                # re-check tts cache
                self._cfg.tts_cache_check()
            if is_sub_dict('proxy', diff):
                # re-init proxy
                self._cfg.proxies_init()
            if is_sub_dict('mpd', diff):
                # reconnect to mpd
                self._mpd.reload()
            if is_sub_dict('settings', diff):
                # reload terminal
                self.call_terminal_call('reload', save_time=False)
            self._cfg.print_cfg_change()
            self._cfg.config_save()


def is_sub_dict(key, data: dict):
    return isinstance(data.get(key), dict) and data[key]
