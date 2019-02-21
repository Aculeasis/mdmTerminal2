#!/usr/bin/env python3

import stts
from config import ConfigHandler
from duplex_mode import DuplexMode
from languages import LOADER as LNG
from lib import STT, TTS
from lib.messenger import Messenger
from lib.proxy import proxies
from lib.publisher import PubSub
from listener import Listener
from logger import Logger, INFO
from modules_manager import ModuleManager
from music_controls import music_constructor
from notifier import MajordomoNotifier
from owner import Owner
from player import Player
from plugins import Plugins
from server import server_constructor
from terminal import MDTerminal
from updater import Updater


class Loader(Owner):
    def __init__(self, init_cfg: dict, path: dict, die_in):
        super().__init__(die_in)
        self._music_constructor = music_constructor
        self._server_constructor = server_constructor
        self._messenger = Messenger()
        self._pub = PubSub()

        self._stt_providers = STT.PROVIDERS
        self._tts_providers = TTS.PROVIDERS

        self._cfg = ConfigHandler(cfg=init_cfg, path=path, owner=self)

        self._logger = Logger(self._cfg['log'], self)
        self._logger.add('mdmTerminal2')('version {} go!'.format(self._cfg.version_str), INFO)

        self._cfg.configure(self._logger.add('CFG'))
        self._listen = Listener(cfg=self._cfg, owner=self)
        proxies.add_logger(self._logger.add('Proxy'))

        self._notifier = MajordomoNotifier(cfg=self._cfg, log=self._logger.add('Notifier'), owner=self)
        self._tts = stts.TextToSpeech(cfg=self._cfg, log=self._logger.add('TTS'))
        self._play = Player(cfg=self._cfg, log=self._logger.add('Player'), owner=self)
        self._music = self._music_constructor(cfg=self._cfg, logger=self._logger, owner=self)
        self._stt = stts.SpeechToText(cfg=self._cfg, log=self._logger.add('STT'), owner=self)
        self._mm = ModuleManager(cfg=self._cfg, log=self._logger.add('MM'), owner=self)
        self._updater = Updater(cfg=self._cfg, log=self._logger.add('Updater'), owner=self)
        self._terminal = MDTerminal(cfg=self._cfg, log=self._logger.add('Terminal'), owner=self)
        self._server = self._server_constructor(cfg=self._cfg, logger=self._logger, owner=self)
        self._plugins = Plugins(cfg=self._cfg, log=self._logger.add('Plugins'), owner=self)
        self._duplex_mode = DuplexMode(cfg=self._cfg, log=self._logger.add('DuplexMode'), owner=self)

    def start_all_systems(self):
        self._music.start()
        self._play.start()
        self._play.say_info(LNG['hello'], 0, wait=0.5)
        self._stt.start()
        self._cfg.start()
        self._notifier.start()
        self._mm.start()
        self._updater.start()
        self._terminal.start()
        self._server.start()
        self._plugins.start()

    def stop_all_systems(self):
        self._cfg.config_save(final=True)
        self._plugins.stop()
        self._mm.stop()
        self._server.join()
        self._terminal.join()
        self._updater.join()
        self._notifier.join()
        self._duplex_mode.join(20)

        self._play.quiet()
        self._play.kill_popen()
        self._play.say_info(LNG['bye'])

        self._stt.stop()
        self._play.stop()
        self._music.join(20)
        self._logger.join()
        self._pub.join()
        self._messenger.join()
