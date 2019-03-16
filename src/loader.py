#!/usr/bin/env python3

import threading

import stts
from config import ConfigHandler
from duplex_mode import DuplexMode
from languages import LOADER as LNG
from lib import STT, TTS
from lib import volume as volume_
from lib.available_version import available_version_msg
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
from utils import state_cache, Messenger


def is_sub_dict(key, data: dict):
    return isinstance(data.get(key), dict) and data[key]


class Loader(Owner):
    def __init__(self, init_cfg: dict, path: dict, die_in):
        self._die_in = die_in
        self.reload = False
        self._lock = threading.Lock()
        self._stts_lock = threading.Lock()

        self._pub = PubSub()

        self._cfg = ConfigHandler(cfg=init_cfg, path=path, owner=self)
        self._logger = Logger(self._cfg['log'], self)

        self._cfg.configure(self._logger.add('CFG'))
        self._listen = Listener(cfg=self._cfg, owner=self)
        proxies.add_logger(self._logger.add('Proxy'))

        self._notifier = MajordomoNotifier(cfg=self._cfg, log=self._logger.add('Notifier'), owner=self)
        self._tts = stts.TextToSpeech(cfg=self._cfg, log=self._logger.add('TTS'))
        self._play = Player(cfg=self._cfg, log=self._logger.add('Player'), owner=self)
        self._music = music_constructor(cfg=self._cfg, logger=self._logger, owner=self)
        self._stt = stts.SpeechToText(cfg=self._cfg, log=self._logger.add('STT'), owner=self)
        self._mm = ModuleManager(cfg=self._cfg, log=self._logger.add('MM'), owner=self)
        self._updater = Updater(cfg=self._cfg, log=self._logger.add('Updater'), owner=self)
        self._terminal = MDTerminal(cfg=self._cfg, log=self._logger.add('Terminal'), owner=self)
        self._server = server_constructor(cfg=self._cfg, logger=self._logger, owner=self)
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
        self.messenger(self._print_version, None)

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

    def _print_version(self):
        self._logger.add('SYSTEM')(available_version_msg(self._cfg.version_info), INFO)

    def subscribe(self, event, callback, channel='default') -> bool:
        return self._pub.subscribe(event, callback, channel)

    def unsubscribe(self, event, callback, channel='default') -> bool:
        return self._pub.unsubscribe(event, callback, channel)

    def registration(self, event: str, channel='default'):
        return self._pub.registration(event, channel)

    def has_subscribers(self, event: str, channel='default') -> bool:
        return self._pub.has_subscribers(event, channel)

    def sub_call(self, channel: str, event: str, *args, **kwargs):
        return self._pub.sub_call(channel, event, *args, **kwargs)

    @staticmethod
    def messenger(call, callback, *args, **kwargs) -> bool:
        return Messenger(call, callback, *args, **kwargs)()

    def insert_module(self, module) -> bool:
        return self._mm.insert_module(module)

    def extract_module(self, callback) -> bool:
        return self._mm.extract_module(callback)

    def add_stt_provider(self, name: str, entrypoint) -> bool:
        with self._stts_lock:
            if name not in STT.PROVIDERS:
                STT.PROVIDERS[name] = entrypoint
                return True
            return False

    def remove_stt_provider(self, name: str) -> bool:
        with self._stts_lock:
            try:
                del STT.PROVIDERS[name]
            except KeyError:
                return False
            return True

    def add_tts_provider(self, name: str, entrypoint) -> bool:
        with self._stts_lock:
            if name not in TTS.PROVIDERS:
                TTS.PROVIDERS[name] = entrypoint
                return True
            return False

    def remove_tts_provider(self, name: str) -> bool:
        with self._stts_lock:
            try:
                del TTS.PROVIDERS[name]
            except KeyError:
                return False
            return True

    @property
    def duplex_mode_on(self) -> bool:
        return self._duplex_mode.duplex

    def duplex_mode_off(self):
        return self._duplex_mode.off()

    def send_on_duplex_mode(self, data):
        self._duplex_mode.send_on_socket(data)

    def plugins_status(self, state: str) -> dict:
        return self._plugins.status(state)

    def get_plugin(self, name: str) -> object:
        try:
            return self._plugins._modules[name]
        except KeyError:
            raise RuntimeError('Plugin \'{}\' not found'.format(name))
        except Exception as e:
            raise RuntimeError('Error accessing to plugin \'{}\': {}'.format(name, e))

    def say(self, msg: str, lvl: int=2, alarm=None, wait=0, is_file: bool = False, blocking: int=0):
        self._play.say(msg, lvl, alarm, wait, is_file, blocking)

    def play(self, file, lvl: int=2, wait=0, blocking: int=0):
        self._play.play(file, lvl, wait, blocking)

    def say_info(self, msg: str, lvl: int=2, alarm=None, wait=0, is_file: bool = False):
        self._play.say_info(msg, lvl, alarm, wait, is_file)

    def set_lvl(self, lvl: int) -> bool:
        return self._play.set_lvl(lvl)

    def clear_lvl(self):
        self._play.clear_lvl()

    def quiet(self):
        self._play.quiet()

    def full_quiet(self):
        self._play.full_quiet()

    def really_busy(self) -> bool:
        return self._play.really_busy()

    @state_cache(interval=0.008)
    def noising(self) -> bool:
        return self._play.noising()

    def kill_popen(self):
        self._play.kill_popen()

    def listen(self, hello: str = '', deaf: bool = True, voice: bool = False) -> str:
        return self._stt.listen(hello, deaf, voice)

    def voice_record(self, hello: str, save_to: str, convert_rate=None, convert_width=None):
        return self._stt.voice_record(hello, save_to, convert_rate, convert_width)

    def voice_recognition(self, audio, quiet: bool=False, fusion=None) -> str:
        return self._stt.voice_recognition(audio, quiet, fusion)

    @property
    def max_mic_index(self) -> int:
        return self._stt.max_mic_index

    @property
    def mic_index(self) -> int:
        return self._stt.get_mic_index()

    def phrase_from_files(self, files: list) -> tuple:
        return self._stt.phrase_from_files(files)

    @property
    def sys_say_chance(self) -> bool:
        return self._stt.sys_say.chance

    def music_play(self, uri):
        self._music.play(uri)

    def music_pause(self, paused=None):
        self._music.pause(paused)

    @property
    def music_plays(self) -> bool:
        return self._music.plays

    @property
    def music_volume(self):
        return self._music.volume

    @music_volume.setter
    def music_volume(self, vol):
        self._music.volume = vol

    @property
    def music_real_volume(self):
        return self._music.real_volume

    @music_real_volume.setter
    def music_real_volume(self, vol):
        self._music.real_volume = vol

    @property
    def music_track_name(self) -> str or None:
        return self._music.get_track_name()

    def tts(self, msg, realtime: bool = True):
        return self._tts.tts(msg, realtime)

    def ask_again_callback(self):
        self._pub.call('ask_again')

    def voice_activated_callback(self):
        self._pub.call('voice_activated')

    def speech_recognized_callback(self, status: bool):
        if status and self._cfg.gts('alarm_recognized'):
            self.play(self._cfg.path['bimp'])
        self._pub.call('speech_recognized_{}success'.format('' if status else 'un'))

    def record_callback(self, start_stop: bool):
        self._pub.call('start_record' if start_stop else 'stop_record')

    def say_callback(self, start_stop: bool):
        self._pub.call('start_talking' if start_stop else 'stop_talking')

    def speech_recognized(self, start_stop: bool):
        self._pub.call('start_recognized' if start_stop else 'stop_recognized')

    def music_status_callback(self, status: str):
        self._pub.call('music_status', status if status is not None else 'error')

    def music_volume_callback(self, volume: int):
        self._pub.call('music_volume', volume if volume is not None else -1)

    def volume_callback(self, volume: int):
        self._pub.call('volume', volume)

    def send_to_srv(self, qry: str, username=None) -> str:
        return self._notifier.send(qry, username)

    @property
    def srv_ip(self) -> str:
        return self._cfg['smarthome']['ip']

    @property
    def outgoing_available(self) -> bool:
        return self._cfg['smarthome']['ip'] or self._duplex_mode.duplex

    def update(self):
        self._updater.update()

    def manual_rollback(self):
        self._updater.manual_rollback()

    def modules_tester(self, phrase: str, call_me=None, model=None):
        return self._mm.tester(phrase, call_me, model)

    def die_in(self, wait, reload=False):
        self.reload = reload
        self._die_in(wait)

    @property
    def get_volume_status(self) -> dict:
        music_volume = self._music.real_volume
        return {'volume': self.get_volume(), 'music_volume': music_volume if music_volume is not None else -1}

    def terminal_call(self, cmd: str, data='', lvl: int=0, save_time: bool=True):
        self._terminal.call(cmd, data, lvl, save_time)

    def chrome_listen(self, interrupt_check, callback):
        return self._listen.chrome_listen(interrupt_check, callback)

    def get_detector(self, source_or_mic, vad_mode=None, vad_lvl=None, energy_lvl=None, energy_dynamic=None):
        return self._listen.get_detector(source_or_mic, vad_mode, vad_lvl, energy_lvl, energy_dynamic)

    def listener_listen(self, r=None, mic=None, detector=None):
        return self._listen.listen(r, mic, detector)

    def background_listen(self):
        return self._listen.background_listen()

    def get_volume(self) -> int:
        control = self._cfg.gt('volume', 'line_out', '')
        card = self._cfg.gt('volume', 'card', 0)
        if not control or control == volume_.UNDEFINED:
            return -2
        return volume_.get_volume(control, card)

    def set_volume(self, vol) -> int:
        control = self._cfg.gt('volume', 'line_out', '')
        card = self._cfg.gt('volume', 'card', 0)
        if not control or control == volume_.UNDEFINED:
            return -2
        try:
            return volume_.set_volume(vol, control, card)
        except RuntimeError:
            return -1

    def settings_from_srv(self, cfg: str or dict) -> dict:
        # Reload modules if their settings could be changes
        with self._lock:
            diff = self._cfg.update_from_external(cfg)
            reload_terminal = False
            if diff is None:
                self._cfg.print_cfg_no_change()
                return {}
            lang, lang_check = None, None
            if is_sub_dict('settings', diff) and ('lang' in diff['settings'] or 'lang_check' in diff['settings']):
                # re-init lang
                lang = diff['settings'].pop('lang', None)
                lang_check = diff['settings'].pop('lang_check', None)
                self._cfg.lang_init()
                if lang:
                    # reload phrases
                    self._stt.reload()
                    # reload modules
                    self._mm.reload()
            if is_sub_dict('models', diff) and 'allow' in diff['models']:
                # reload models. Reload terminal - later
                self._cfg.models_load()
                reload_terminal = True
            if is_sub_dict('log', diff):
                # reload logger
                self._logger.reload()
            if is_sub_dict('cache', diff):
                # re-check tts cache
                self._cfg.tts_cache_check()
            if is_sub_dict('proxy', diff):
                # re-init proxy
                self._cfg.proxies_init()
            if is_sub_dict('music', diff):
                # reconfigure music server
                self.music_reload()
            if is_sub_dict('smarthome', diff):
                if 'disable_server' in diff['smarthome']:
                    # handle [smarthome] disable_server
                    self.messenger(self.server_reload, None)
                # resubscribe
                self._notifier.reload(diff)
            if is_sub_dict('noise_suppression', diff):
                # reconfigure APM. Reload terminal - later
                self._cfg.apm_configure()
                reload_terminal = True
            if is_sub_dict('settings', diff) or is_sub_dict('listener', diff) or reload_terminal:
                # reload terminal
                self.terminal_call('reload', save_time=False)

            # restore lang's
            if lang is not None:
                diff['settings']['lang'] = lang
            if lang_check is not None:
                diff['settings']['lang_check'] = lang_check

            # check and reload plugins
            self._plugins.reload(diff)
            self._cfg.print_cfg_change()
            self._cfg.config_save()
            return diff

    def music_reload(self):
        self._music = music_constructor(self._cfg, self._logger, self, self._music)

    def server_reload(self):
        self._server = server_constructor(self._cfg, self._logger, self, self._server)
