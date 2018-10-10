#!/usr/bin/env python3

import stts
from config import ConfigHandler
from logger import Logger
from modules_manager import ModuleManager
from mpd_control import MPDControl
from player import Player
from server import MDTServer
from terminal import MDTerminal


class Loader:
    def __init__(self, init_cfg: dict, path: dict, die_in):
        self._die_in = die_in
        self.reload = False

        self._cfg = ConfigHandler(cfg=init_cfg, path=path)
        self._logger = Logger(self._cfg['log'])
        self._cfg.configure(self._logger.add('CFG'))

        self._tts = stts.TextToSpeech(cfg=self._cfg, log=self._logger.add('TTS')).tts

        self._play = Player(cfg=self._cfg, log=self._logger.add('Player'), tts=self._tts)

        self._mpd = MPDControl(cfg=self._cfg['mpd'], log=self._logger.add('MPD'), last_play=self._play.last_activity)

        self._stt = stts.SpeechToText(cfg=self._cfg, play_=self._play, log=self._logger.add('STT'), tts=self._tts)

        self._mm = ModuleManager(
            log=self._logger.add_plus('MM'), cfg=self._cfg, die_in=self.die_in, say=self._play.say
        )

        self._terminal = MDTerminal(
            cfg=self._cfg, play_=self._play, stt=self._stt,
            log=self._logger.add('Terminal'), handler=self._mm.tester
        )

        self._server = MDTServer(
            cfg=self._cfg, log=self._logger.add('Server'),
            play=self._play, terminal=self._terminal, die_in=self.die_in, stt=self._stt
        )

    def start(self):
        mpd_err = False
        try:
            if self._cfg['mpd'].get('control', 0):
                self._mpd.start()
        except RuntimeError:
            mpd_err = True
        self._play.start(self._mpd)
        if mpd_err:
            self._play.say('Ошибка подключения к MPD-серверу')
        self._play.say('Приветствую. Голосовой терминал Мажордомо настраивается, три... два... один...', 0, wait=0.5)
        self._stt.start()
        self._cfg.join_low_say(self._play.say)
        self._mm.start()
        self._terminal.start()
        self._server.start()

    def stop(self):
        self._mm.save()
        self._server.join()
        self._terminal.join()

        self._play.quiet()
        self._play.kill_popen()
        self._play.say('Голосовой терминал мажордомо завершает свою работу.')

        self._stt.stop()
        self._play.stop()
        self._mpd.join()
        self._logger.join()

    def die_in(self, wait, reload=False):
        self.reload = reload
        self._die_in(wait)
