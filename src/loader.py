#!/usr/bin/env python3

import threading

import stts
from config import ConfigHandler
from languages import LOADER as LNG
from lib.proxy import proxies
from lib.publisher import PubSub
from logger import Logger
from modules_manager import ModuleManager
from mpd_control import MPDControl
from notifier import MajordomoNotifier
from owner import Owner
from player import Player
from server import MDTServer
from terminal import MDTerminal
from updater import Updater
from listener import Listener


class Loader(Owner):
    def __init__(self, init_cfg: dict, path: dict, die_in):
        self._die_in = die_in
        self.reload = False
        self._lock = threading.Lock()

        self._pub = PubSub()
        self._cfg = ConfigHandler(cfg=init_cfg, path=path, owner=self)
        self._logger = Logger(self._cfg['log'], self)
        self._cfg.configure(self._logger.add('CFG'))
        self._listen = Listener(cfg=self._cfg, owner=self)
        proxies.add_logger(self._logger.add('Proxy'))

        self._notifier = MajordomoNotifier(cfg=self._cfg['majordomo'], log=self._logger.add('Notifier'), owner=self)
        self._tts = stts.TextToSpeech(cfg=self._cfg, log=self._logger.add('TTS'))
        self._play = Player(cfg=self._cfg, log=self._logger.add('Player'), owner=self)
        self._mpd = MPDControl(cfg=self._cfg['mpd'], log=self._logger.add('MPD'), owner=self)
        self._stt = stts.SpeechToText(cfg=self._cfg, log=self._logger.add('STT'), owner=self)
        self._mm = ModuleManager(log=self._logger.add_plus('MM'), cfg=self._cfg, owner=self)
        self._updater = Updater(cfg=self._cfg, log=self._logger.add('Updater'), owner=self)
        self._terminal = MDTerminal(cfg=self._cfg, log=self._logger.add('Terminal'), owner=self)
        self._server = MDTServer(cfg=self._cfg, log=self._logger.add_plus('Server'), owner=self)

    def start_all_systems(self):
        self._pub.start()
        self._mpd.start()
        self._play.start()
        self._play.say_info(LNG['hello'], 0, wait=0.5)
        self._stt.start()
        self._cfg.start()
        self._notifier.start()
        self._mm.start()
        self._updater.start()
        self._terminal.start()
        self._server.start()

    def stop_all_systems(self):
        self._mm.save()
        self._server.join()
        self._terminal.join()
        self._updater.join()
        self._notifier.join()

        self._play.quiet()
        self._play.kill_popen()
        self._play.say_info(LNG['bye'])

        self._stt.stop()
        self._play.stop()
        self._mpd.join(20)
        self._logger.join()
        self._pub.join()
