from utils import state_cache


class Owner:
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
        raise NotImplementedError

    def unsubscribe(self, event, callback, channel='default') -> bool:
        """
        Отказ от подписки на событие или события,
        все параметры и результат аналогичны subscribe.
        """
        raise NotImplementedError

    def registration(self, event: str, channel='default'):
        """
        Создание вызываемого объекта для активации события.
        :param event: не пустое имя события.
        :param channel: канал.
        :return: вернет объект вызов которого активирует все коллбэки подписанные на событие,
        или None если event некорректный.
        """
        raise NotImplementedError

    def has_subscribers(self, event: str, channel='default') -> bool:
        """
        :param event: имя события.
        :param channel: канал.
        :return: есть ли у события подписчики.
        """
        raise NotImplementedError

    def sub_call(self, channel: str, event: str, *args, **kwargs):
        """
        Активирует событие напрямую.
        :param channel: канал.
        :param event: событие.
        :param args: args.
        :param kwargs: kwargs.
        """
        raise NotImplementedError

    @staticmethod
    def messenger(call, callback, *args, **kwargs) -> bool:
        """
        Вызывает call (с параметрами) в отдельном треде.
        Если callback callable, вызовет его с результатом вызова (1 аргумент).
        :param call: callable.
        :param callback: callable or None.
        :param args: args.
        :param kwargs: kwargs.
        :return: запущено.
        """
        raise NotImplementedError

    def insert_module(self, module) -> bool:
        """
        Добавляет динамический модуль.
        Динамические модули проритетнее обычных и обрабатываются в порядке LIFO,
        также ими нельзя управлять и их настройки не сохраняются.
        :param module: экземпляр modules_manager.DynamicModule.
        :return: был ли модуль добавлен.
        """
        raise NotImplementedError

    def extract_module(self, callback) -> bool:
        """
        Удаляет динамический модуль по его коллбэку.
        :param callback: коллбэк динамического модуля.
        :return: был ли модуль удален.
        """
        raise NotImplementedError

    def add_stt_provider(self, name: str, entrypoint) -> bool:
        """
        Добавляет speech-to-text провайдера.
        :param name: имя провайдера.
        :param entrypoint: конструктор, ожидается что это объект класса и потомок lib.STT.BaseSTT.
        :return: успешность операции.
        """
        raise NotImplementedError

    def remove_stt_provider(self, name: str) -> bool:
        """
        Удаляет speech-to-text провайдера.
        :param name: имя провайдера.
        :return: успешность операции.
        """
        raise NotImplementedError

    def add_tts_provider(self, name: str, entrypoint) -> bool:
        """
        Добавляет text-to-speech провайдера.
        :param name: имя провайдера.
        :param entrypoint: конструктор, ожидается что это объект класса и потомок lib.TTS.BaseTTS.
        :return: успешность операции.
        """
        raise NotImplementedError

    def remove_tts_provider(self, name: str) -> bool:
        """
        Удаляет text-to-speech провайдера.
        :param name: имя провайдера.
        :return: успешность операции.
        """
        raise NotImplementedError

    @property
    def duplex_mode_on(self) -> bool:
        """
        Duplex mode активен.
        """
        raise NotImplementedError

    def duplex_mode_off(self):
        """
        Закрыть активное соединение в duplex mode (если есть).
        :return: None
        """
        raise NotImplementedError

    def send_on_duplex_mode(self, data):
        """
        Отправить данные через подключение в duplex mode.
        Сработает только если self.duplex_mode_on = True.
        Может вызвать RuntimeError.
        :param data: bytes, str or dict
        """
        raise NotImplementedError

    def plugins_status(self, state: str) -> dict:
        """
        Имена и абсолютные пути до плагинов в определенном состоянии.
        :param state: all, deprecated or broken
        :return: {name: path,}
        """
        raise NotImplementedError

    def get_plugin(self, name: str) -> object:
        """
        Возвращает ссылку на запущенный плагин или бросает RuntimeError.
        :param name: имя плагина.
        :return: Ссылка на плагин.
        """
        raise NotImplementedError

    def say(self, msg: str, lvl: int = 2, alarm=None, wait=0, is_file: bool = False, blocking: int = 0):
        raise NotImplementedError

    def play(self, file, lvl: int = 2, wait=0, blocking: int = 0):
        raise NotImplementedError

    def say_info(self, msg: str, lvl: int = 2, alarm=None, wait=0, is_file: bool = False):
        raise NotImplementedError

    def set_lvl(self, lvl: int) -> bool:
        raise NotImplementedError

    def clear_lvl(self):
        raise NotImplementedError

    def quiet(self):
        raise NotImplementedError

    def full_quiet(self):
        raise NotImplementedError

    def really_busy(self) -> bool:
        raise NotImplementedError

    @state_cache(interval=0.008)
    def noising(self) -> bool:
        raise NotImplementedError

    def kill_popen(self):
        raise NotImplementedError

    def listen(self, hello: str = '', deaf: bool = True, voice: bool = False) -> str:
        raise NotImplementedError

    def voice_record(self, hello: str, save_to: str, convert_rate=None, convert_width=None):
        raise NotImplementedError

    def voice_recognition(self, audio, quiet: bool = False, fusion=None) -> str:
        raise NotImplementedError

    @property
    def max_mic_index(self) -> int:
        raise NotImplementedError

    @property
    def mic_index(self) -> int:
        raise NotImplementedError

    def phrase_from_files(self, files: list) -> tuple:
        raise NotImplementedError

    @property
    def sys_say_chance(self) -> bool:
        raise NotImplementedError

    def music_play(self, uri):
        raise NotImplementedError

    def music_pause(self, paused=None):
        raise NotImplementedError

    @property
    def music_plays(self) -> bool:
        raise NotImplementedError

    @property
    def music_volume(self):
        raise NotImplementedError

    @music_volume.setter
    def music_volume(self, vol):
        raise NotImplementedError

    @property
    def music_real_volume(self):
        raise NotImplementedError

    @music_real_volume.setter
    def music_real_volume(self, vol):
        raise NotImplementedError

    @property
    def music_track_name(self) -> str or None:
        raise NotImplementedError

    def tts(self, msg, realtime: bool = True):
        raise NotImplementedError

    def ask_again_callback(self):
        raise NotImplementedError

    def voice_activated_callback(self):
        raise NotImplementedError

    def speech_recognized_callback(self, status: bool):
        raise NotImplementedError

    def record_callback(self, start_stop: bool):
        raise NotImplementedError

    def say_callback(self, start_stop: bool):
        raise NotImplementedError

    def speech_recognized(self, start_stop: bool):
        raise NotImplementedError

    def music_status_callback(self, status: str):
        raise NotImplementedError

    def music_volume_callback(self, volume: int):
        raise NotImplementedError

    def volume_callback(self, volume: int):
        raise NotImplementedError

    def send_to_srv(self, qry: str, username=None) -> str:
        raise NotImplementedError

    @property
    def srv_ip(self) -> str:
        raise NotImplementedError

    @property
    def outgoing_available(self) -> bool:
        raise NotImplementedError

    def update(self):
        raise NotImplementedError

    def manual_rollback(self):
        raise NotImplementedError

    def modules_tester(self, phrase: str, call_me=None, model=None):
        raise NotImplementedError

    def die_in(self, wait, reload=False):
        raise NotImplementedError

    @property
    def get_volume_status(self) -> dict:
        raise NotImplementedError

    def terminal_call(self, cmd: str, data='', lvl: int = 0, save_time: bool = True):
        raise NotImplementedError

    def recognition_forever(self, interrupt_check: callable, callback: callable):
        raise NotImplementedError

    def get_detector(self, source_or_mic, vad_mode=None, vad_lvl=None, energy_lvl=None, energy_dynamic=None):
        raise NotImplementedError

    def listener_listen(self, r=None, mic=None, detector=None):
        raise NotImplementedError

    def background_listen(self):
        raise NotImplementedError

    def get_volume(self) -> int:
        """
        Вернет текущую громкость системы 0..100 или код ошибки.
        Ошибки: -2 не настроено, -1 ошибка получения.
        :return:  громкость или код ошибки.
        """
        raise NotImplementedError

    def set_volume(self, vol) -> int:
        """
        Изменяет системную громкость, вернет громкость иди код ошибки.
        Ошибки: -2 не настроено, -1 ошибка установки.
        :param vol: громкость 0..100, int или то что можно преобразовать в int.
        :return:  громкость или код ошибки.
        """
        raise NotImplementedError

    def settings_from_srv(self, cfg: str or dict) -> dict:
        # Reload modules if their settings could be changes
        raise NotImplementedError

    def music_reload(self):
        raise NotImplementedError

    def server_reload(self):
        raise NotImplementedError
