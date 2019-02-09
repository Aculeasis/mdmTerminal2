import threading

from lib import volume as volume_
from utils import state_cache


class Owner:
    def __init__(self, die_in=lambda x: None):
        self._die_in = die_in
        self.reload = False
        self._lock = threading.Lock()
        self._stts_lock = threading.Lock()

    def subscribe(self, event, callback, channel='default') -> bool:
        """
        Оформление подписки на событие или события. Можно подписаться сразу на много событий или
        подписать много коллбэков на одно событие передав их списком, но передать сразу 2 списка нельзя.
        Важно: Вызываемый код не должен выполняться долго т.к. он заблокирует другие коллбэки.

        :param event: не пустое имя события в str или список событий.
        :param callback: ссылка на объект который можно вызвать или список таких объектов,
        при вызове передаются: имя события, *args, **kwargs.
        :param channel: канал.
        :return: будет ли оформлена подписка.
        """
        return self._pub.subscribe(event, callback, channel)

    def unsubscribe(self, event, callback, channel='default') -> bool:
        """
        Отказ от подписки на событие или события,
        все параметры и результат аналогичны subscribe.
        """
        return self._pub.unsubscribe(event, callback, channel)

    def registration(self, event: str, channel='default'):
        """
        Создание вызываемого объекта для активации события.
        :param event: не пустое имя события.
        :param channel: канал.
        :return: вернет объект вызов которого активирует все коллбэки подписанные на событие,
        или None если event некорректный.
        """
        return self._pub.registration(event, channel)

    def has_subscribers(self, event: str, channel='default') -> bool:
        """
        :param event: имя события.
        :param channel: канал.
        :return: есть ли у события подписчики.
        """
        return self._pub.has_subscribers(event, channel)

    def sub_call(self, channel: str, event: str, *args, **kwargs):
        """
        Активирует событие напрямую.
        :param channel: канал.
        :param event: событие.
        :param args: args.
        :param kwargs: kwargs.
        """
        return self._pub.sub_call(channel, event, *args, **kwargs)

    def insert_module(self, module) -> bool:
        """
        Добавляет динамический модуль.
        Динамические модули проритетнее обычных и обрабатываются в порядке LIFO,
        также ими нельзя управлять и их настройки не сохраняются.
        :param module: экземпляр modules_manager.DynamicModule.
        :return: был ли модуль добавлен.
        """
        return self._mm.insert_module(module)

    def extract_module(self, callback) -> bool:
        """
        Удаляет динамический модуль по его коллбэку.
        :param callback: коллбэк динамического модуля.
        :return: был ли модуль удален.
        """
        return self._mm.extract_module(callback)

    def add_stt_provider(self, name: str, entrypoint) -> bool:
        """
        Добавляет speech-to-text провайдера.
        :param name: имя провайдера.
        :param entrypoint: конструктор, ожидается что это объект класса и потомок lib.STT.BaseSTT.
        :return: успешность операции.
        """
        with self._stts_lock:
            if name not in self._stt_providers:
                self._stt_providers[name] = entrypoint
                return True
            return False

    def remove_stt_provider(self, name: str) -> bool:
        """
        Удаляет speech-to-text провайдера.
        :param name: имя провайдера.
        :return: успешность операции.
        """
        with self._stts_lock:
            try:
                del self._stt_providers[name]
            except KeyError:
                return False
            return True

    def add_tts_provider(self, name: str, entrypoint) -> bool:
        """
        Добавляет text-to-speech провайдера.
        :param name: имя провайдера.
        :param entrypoint: конструктор, ожидается что это объект класса и потомок lib.TTS.BaseTTS.
        :return: успешность операции.
        """
        with self._stts_lock:
            if name not in self._tts_providers:
                self._tts_providers[name] = entrypoint
                return True
            return False

    def remove_tts_provider(self, name: str) -> bool:
        """
        Удаляет text-to-speech провайдера.
        :param name: имя провайдера.
        :return: успешность операции.
        """
        with self._stts_lock:
            try:
                del self._tts_providers[name]
            except KeyError:
                return False
            return True

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

    def mpd_play(self, uri):
        self._mpd.play(uri)

    def mpd_pause(self, paused=None):
        self._mpd.pause(paused)

    @property
    def mpd_plays(self) -> bool:
        return self._mpd.plays

    @property
    def mpd_volume(self):
        return self._mpd.volume

    @mpd_volume.setter
    def mpd_volume(self, vol):
        self._mpd.volume = vol

    @property
    def mpd_real_volume(self):
        return self._mpd.real_volume

    @mpd_real_volume.setter
    def mpd_real_volume(self, vol):
        self._mpd.real_volume = vol

    def tts(self, msg, realtime: bool = True):
        return self._tts.tts(msg, realtime)

    def ask_again_callback(self):
        self._pub.call('ask_again')

    def voice_activated_callback(self):
        self._pub.call('voice_activated')

    def speech_recognized_success_callback(self):
        self._pub.call('speech_recognized_success')

    def record_callback(self, start_stop: bool):
        self._pub.call('start_record' if start_stop else 'stop_record')

    def say_callback(self, start_stop: bool):
        self._pub.call('start_talking' if start_stop else 'stop_talking')

    def speech_recognized(self, start_stop: bool):
        self._pub.call('start_recognized' if start_stop else 'stop_recognized')

    def mpd_status_callback(self, status: str):
        self._pub.call('mpd_status', status if status is not None else 'error')

    def mpd_volume_callback(self, volume: int):
        self._pub.call('mpd_volume', volume if volume is not None else -1)

    def volume_callback(self, volume: int):
        self._pub.call('volume', volume)

    def send_to_srv(self, qry: str, username=None) -> str:
        return self._notifier.send(qry, username)

    def send_to_mjd(self, qry: str, username=None) -> str:
        # TODO: Deprecated
        return self.send_to_srv(qry, username)

    @property
    def srv_ip(self) -> str:
        return self._cfg.gt('majordomo', 'ip', '')

    @property
    def mjd_ip(self) -> str:
        # TODO: Deprecated
        return self.srv_ip

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
        mpd_volume = self._mpd.real_volume
        return {'volume': self.get_volume(), 'mpd_volume': mpd_volume if mpd_volume is not None else -1}

    def terminal_call(self, cmd: str, data='', lvl: int=0, save_time: bool=True):
        self._terminal.call(cmd, data, lvl, save_time)

    def chrome_listen(self, interrupt_check, callback):
        return self._listen.chrome_listen(interrupt_check, callback)

    def get_detector(self, source_or_mic, vad_mode=None, vad_lvl=None, energy_lvl=None, energy_dynamic=None):
        return self._listen.get_detector(source_or_mic, vad_mode, vad_lvl, energy_lvl, energy_dynamic)

    def listener_listen(self, r=None, mic=None, detector=None, timeout=10):
        return self._listen.listen(r, mic, detector, timeout)

    def background_listen(self):
        return self._listen.background_listen()

    def get_volume(self) -> int:
        """
        Вернет текущую громкость системы 0..100 или код ошибки.
        Ошибки: -2 не настроено, -1 ошибка получения.
        :return:  громкость или код ошибки.
        """
        control = self._cfg.gt('volume', 'line_out', '')
        card = self._cfg.gt('volume', 'card', 0)
        if not control or control == volume_.UNDEFINED:
            return -2
        return volume_.get_volume(control, card)

    def set_volume(self, vol) -> int:
        """
        Изменяет системную громкость, вернет громкость иди код ошибки.
        Ошибки: -2 не настроено, -1 ошибка установки.
        :param vol: громкость 0..100, int или то что можно преобразовать в int.
        :return:  громкость или код ошибки.
        """
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
            if is_sub_dict('mpd', diff):
                # reconnect to mpd and resubscribe
                self._mpd.reload()
            if is_sub_dict('majordomo', diff):
                # resubscribe
                self._notifier.reload()
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

    def settings_from_mjd(self, cfg: str):
        # TODO: Deprecated
        return self.settings_from_srv(cfg)


def is_sub_dict(key, data: dict):
    return isinstance(data.get(key), dict) and data[key]
