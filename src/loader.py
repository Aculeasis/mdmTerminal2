#!/usr/bin/env python3

import threading
import time

import logger
import stts
from backup import Backup
from config import ConfigHandler
from discovery_server import DiscoveryServer
from duplex_mode import DuplexPool
from languages import F
from lib import STT, TTS
from lib import volume as volume_
from lib.available_version import available_version_msg
from lib.proxy import proxies
from lib.publisher import PubSub
from listener import Listener
from modules_manager import ModuleManager
from music_controls import music_constructor
from notifier import MajordomoNotifier
from owner import Owner
from player import Player
from plugins import Plugins
from server import server_constructor
from terminal import MDTerminal
from updater import Updater
from utils import state_cache, Messenger, pretty_time, SignalHandlerDummy


def is_sub_dict(key, data: dict):
    return isinstance(data.get(key), dict) and data[key]


class Loader(Owner):
    def __init__(self, init_cfg: dict, path: dict, sig: SignalHandlerDummy):
        self._sig = sig
        self.reload = False
        self._restore_filename = None
        self._lock = threading.Lock()
        self._stts_lock = threading.Lock()
        self._join_lock = threading.Lock()

        self._pub = PubSub()
        self._sig.set_wakeup_callback(lambda: self.sub_call('default', 'terminal_stop', True))

        self._logger = logger.Logger(self)
        proxies.add_logger(self._logger.add('Proxy'))
        self._cfg = ConfigHandler(cfg=init_cfg, path=path, log=self._logger.add('CFG'), owner=self)
        self._logger.init(cfg=self._cfg, owner=self)
        self._log = self._logger.add('SYSTEM')

        self._listen = Listener(cfg=self._cfg, log=self._logger.add('REC'), owner=self)
        self._notifier = MajordomoNotifier(cfg=self._cfg, log=self._logger.add('Notifier'), owner=self)
        self._tts = stts.TextToSpeech(cfg=self._cfg, log=self._logger.add('TTS'))
        self._play = Player(cfg=self._cfg, log=self._logger.add('Player'), owner=self)
        self._music = music_constructor(cfg=self._cfg, logger=self._logger, owner=self)
        self._stt = stts.SpeechToText(cfg=self._cfg, log=self._logger.add('STT'), owner=self)
        self._mm = ModuleManager(cfg=self._cfg, log=self._logger.add('MM'), owner=self)
        self._updater = Updater(cfg=self._cfg, log=self._logger.add('Updater'), owner=self)
        self._backup = Backup(cfg=self._cfg, log=self._logger.add('Backup'), owner=self)
        self._terminal = MDTerminal(cfg=self._cfg, log=self._logger.add('Terminal'), owner=self)
        self._server = server_constructor(cfg=self._cfg, logger=self._logger, owner=self)
        self._plugins = Plugins(cfg=self._cfg, log=self._logger.add('Plugins'), owner=self)
        self._duplex_pool = DuplexPool(cfg=self._cfg, log=self._logger.add('DP'), owner=self)

        self._discovery = DiscoveryServer(cfg=self._cfg, log=self._logger.add('Discovery'))

    def start_all_systems(self):
        self._music.start()
        self._play.start()
        self._play.say_info(F('Приветствую. Голосовой терминал настраивается, три... два... один...'), 0, wait=0.5)
        self._stt.start()
        self._cfg.start()
        self._notifier.start()
        self._mm.start()
        self._updater.start()
        self._terminal.start()
        self._server.start()
        self._discovery.start()
        self._backup.start()
        self._plugins.start()

        self.messenger(lambda: self.log(available_version_msg(self._cfg.version_info), logger.INFO), None)
        self.sub_call('default', 'version', self._cfg.version_str)
        self.volume_callback(self.get_volume())

    def stop_all_systems(self):
        self._cfg.config_save(final=True)
        self._plugins.stop()
        self._mm.stop()
        self.join_thread(self._discovery)
        self.join_thread(self._server)
        self.join_thread(self._terminal)
        self.join_thread(self._backup)
        self.join_thread(self._updater)
        self.join_thread(self._notifier)
        self.join_thread(self._duplex_pool)

        self._play.quiet()
        self._play.kill_popen()
        self._play.say_info(F('Голосовой терминал завершает свою работу.'))

        self._stt.stop()
        self._play.stop()
        self.join_thread(self._music)

        if self._restore_filename:
            self._backup.restore(self._restore_filename)
            self._restore_filename = ''

        self.join_thread(self._logger.remote_log)
        self._pub.stopping = True
        self._logger.join()
        self._pub.join()

        self._pub.report()

    def log(self, msg: str, lvl=logger.DEBUG):
        self._log(msg, lvl)

    def join_thread(self, obj):
        def obj_log(msg_: str, lvl=logger.DEBUG):
            if log_present:
                obj.log(msg_, lvl)

        def diagnostic_msg() -> str:
            _call = getattr(obj, 'diagnostic_msg', None)
            return ' {}'.format(_call()) if callable(_call) else ''

        with self._join_lock:
            close_signal = getattr(obj, 'close_signal', None)
            if close_signal:
                close_signal()
            if not obj.work:
                return
            log_present = callable(getattr(obj, 'log', None))
            obj.work = False
            obj_log('stopping...')
            stop_time = time.time()
            obj.join()
            stop_time = time.time() - stop_time
            if not obj.is_alive():
                obj_log('stop.', logger.INFO)
            else:
                obj_log('stopping error.', logger.ERROR)
                name_ = '.'.join(getattr(obj.log, 'name', [''])) if log_present else None
                name_ = name_ or str(obj)
                msg = 'Thread \'{}\' stuck and not stopping in {}!{}'.format(
                    name_, pretty_time(stop_time), diagnostic_msg())
                self.log(msg, logger.ERROR)

    def subscribe(self, event, callback, channel='default') -> bool:
        return self._pub.subscribe(event, callback, channel)

    def unsubscribe(self, event, callback, channel='default') -> bool:
        return self._pub.unsubscribe(event, callback, channel)

    def registration(self, event: str, channel='default'):
        return self._pub.registration(event, channel)

    def has_subscribers(self, event: str, channel='default') -> bool:
        return self._pub.has_subscribers(event, channel)

    def events_list(self, channel='default') -> list:
        return self._pub.events_list(channel)

    def send_notify(self, event: str, *args, **kwargs):
        return self._pub.sub_call('default', event, *args, **kwargs)

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

    def tts_providers(self) -> list:
        with self._stts_lock:
            return list(TTS.PROVIDERS.keys())

    def stt_providers(self) -> list:
        with self._stts_lock:
            return list(STT.PROVIDERS.keys())

    def is_tts_provider(self, name: str) -> bool:
        return name in TTS.PROVIDERS

    def is_stt_provider(self, name: str) -> bool:
        return name in STT.PROVIDERS

    def plugins_status(self, state: str) -> dict:
        return self._plugins.status(state)

    def get_plugin(self, name: str) -> object:
        try:
            return self._plugins.modules[name]
        except KeyError:
            raise RuntimeError('Plugin \'{}\' not found'.format(name))
        except Exception as e:
            raise RuntimeError('Error accessing to plugin \'{}\': {}'.format(name, e))

    def list_notifications(self) -> list:
        return self._notifier.list_notifications()

    def add_notifications(self, events: list, is_self=False) -> list:
        return self._notifier.add_notifications(events, is_self)

    def remove_notifications(self, events: list) -> list:
        return self._notifier.remove_notifications(events)

    def say(self, msg: str, lvl: int = 2, alarm=None, wait=0, is_file: bool = False, blocking: int = 0):
        self._play.say(msg, lvl, alarm, wait, is_file, blocking)

    def play(self, file, lvl: int = 2, wait=0, blocking: int = 0):
        self._play.play(file, lvl, wait, blocking)

    def say_info(self, msg: str, lvl: int = 2, alarm=None, wait=0, is_file: bool = False):
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

    def listen(self, hello: str = '', deaf: bool = True, voice: bool = False) -> tuple:
        return self._stt.listen(hello, deaf, voice)

    def voice_record(self, hello: str or None, save_to: str, convert_rate=None, convert_width=None, limit=8):
        return self._stt.voice_record(hello, save_to, convert_rate, convert_width, limit)

    def voice_recognition(self, audio, quiet: bool = False, fusion=None) -> str:
        return self._stt.voice_recognition(audio, quiet, fusion)

    @property
    def max_mic_index(self) -> int:
        return self._stt.max_mic_index

    @max_mic_index.setter
    def max_mic_index(self, val: int):
        self._stt.max_mic_index = val

    @property
    def mic_index(self) -> int:
        return self._stt.get_mic_index()

    def phrase_from_files(self, files: list) -> tuple:
        return self._stt.phrase_from_files(files)

    def multiple_recognition(self, file_or_adata, providers: list) -> list:
        return self._stt.multiple_recognition(file_or_adata, providers)

    @property
    def sys_say_chance(self) -> bool:
        return self._stt.sys_say.chance

    def music_state(self) -> str:
        return self._music.state()

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

    @property
    def srv_ip(self) -> str:
        return self._cfg['smarthome']['ip']

    def update(self):
        self._updater.update()

    def manual_rollback(self):
        self._updater.manual_rollback()

    def backup_manual(self):
        self._backup.manual_backup()

    def backup_restore(self, filename: str):
        if not self._restore_filename and filename:
            self._restore_filename = filename
            self.die_in(3, reload=True)

    def backup_list(self) -> list:
        return self._backup.backup_list()

    def modules_tester(self, phrase: str, call_me=None, rms=None, model=None):
        return self._mm.tester(phrase, call_me, rms, model)

    def die_in(self, wait, reload=False):
        self.reload = reload
        self._sig.die_in(wait)

    @property
    def get_volume_status(self) -> dict:
        music_volume = self._music.real_volume
        return {'volume': self.get_volume(), 'music_volume': music_volume if music_volume is not None else -1}

    def terminal_call(self, cmd: str, data='', lvl: int = 0, save_time: bool = True):
        self._terminal.call(cmd, data, lvl, save_time)

    def terminal_listen(self) -> bool:
        return self._terminal.listening

    def recognition_forever(self, interrupt_check: callable, callback: callable):
        return self._listen.recognition_forever(interrupt_check, callback)

    def get_vad_detector(self, source_or_mic, vad_mode=None, vad_lvl=None, energy_lvl=None, energy_dynamic=None):
        return self._listen.get_vad_detector(source_or_mic, vad_mode, vad_lvl, energy_lvl, energy_dynamic)

    def listener_listen(self, r=None, mic=None, vad=None):
        return self._listen.listen(r, mic, vad)

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
            detector_reconfigure = False
            vad_reconfigure = False
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
            if is_sub_dict('update', diff):
                # update 'update' interval
                self._updater.reload()
            if is_sub_dict('backup', diff):
                # update backup interval
                self._backup.reload()
            if is_sub_dict('smarthome', diff):
                if 'allow_addresses' in diff['smarthome']:
                    # re-init allow ip addresses
                    self._cfg.allow_addresses_init()
                if 'disable_server' in diff['smarthome']:
                    # handle [smarthome] disable_server
                    self.messenger(self.server_reload, None)
                # resubscribe
                self._notifier.reload(diff)
                self._duplex_pool.reload()
            if is_sub_dict('noise_suppression', diff):
                # reconfigure APM. Reload terminal - later
                self._cfg.apm_configure()
                reload_terminal = True
            if is_sub_dict('listener', diff):
                reload_terminal = True
                detector_reconfigure = 'detector' in diff['listener']
                vad_reconfigure = bool([key for key in ('vad_mode', 'vad_chrome') if key in diff['listener']])
            if is_sub_dict('settings', diff) or reload_terminal:
                # reload terminal
                # noinspection PyTypeChecker
                self.terminal_call('reload', (detector_reconfigure, vad_reconfigure), save_time=False)

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
