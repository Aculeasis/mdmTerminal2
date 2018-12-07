from lib.volume import get_volume


class Owner:
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

    def noising(self) -> bool:
        return self._play.noising()

    def kill_popen(self):
        self._play.kill_popen()

    @property
    def last_activity(self) -> float:
        return self._play.last_activity()

    def listen(self, hello: str = '', deaf: bool = True, voice: bool = False) -> str:
        return self._stt.listen(hello, deaf, voice)

    def voice_record(self, hello: str, save_to: str, convert_rate=None, convert_width=None):
        return self._stt.voice_record(hello, save_to, convert_rate, convert_width)

    def voice_recognition(self, audio, quiet: bool=False) -> str:
        return self._stt.voice_recognition(audio, quiet)

    def energy_correct(self, r, source):
        return self._stt.energy.correct(r, source)

    def energy_set(self, energy_threshold):
        return self._stt.energy.set(energy_threshold)

    @property
    def max_mic_index(self) -> int:
        return self._stt.max_mic_index

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

    def record_callback(self, start_stop: bool):
        self._notifier.callback(status='start_record' if start_stop else 'stop_record')

    def say_callback(self, start_stop: bool):
        self._notifier.callback(status='start_talking' if start_stop else 'stop_talking')

    def mpd_status_callback(self, status: str):
        self._notifier.callback(status='mpd_{}'.format(status))

    def mpd_volume_callback(self, volume: int):
        self._notifier.callback(mpd_volume=volume)

    def volume_callback(self, volume: int):
        self._notifier.callback(volume=volume)

    def send_to_mjd(self, qry: str) -> str:
        return self._notifier.send(qry)

    @property
    def mjd_ip_set(self) -> bool:
        return self._notifier.ip_set

    def update(self):
        self._updater.update()

    def manual_rollback(self):
        self._updater.manual_rollback()

    def modules_tester(self, phrase: str, call_me=None):
        return self._mm.tester(phrase, call_me)

    def die_in(self, wait, reload=False):
        self.reload = reload
        self._die_in(wait)

    @property
    def get_volume_status(self) -> dict:
        return {'volume': get_volume(self._cfg.gt('volume', 'line_out', '')), 'mpd_volume': self._mpd.real_volume}

    def terminal_call(self, cmd: str, data='', lvl: int=0, save_time: bool=True):
        self._terminal.call(cmd, data, lvl, save_time)

    def settings_from_mjd(self, cfg: str):
        # Reload modules if their settings could be changes
        with self._lock:
            diff = self._cfg.update_from_json(cfg)
            reload_terminal = False
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
                # reconnect to mpd
                self._mpd.reload()
            if is_sub_dict('settings', diff) or reload_terminal:
                # reload terminal
                self.terminal_call('reload', save_time=False)
            self._cfg.print_cfg_change()
            self._cfg.config_save()


def is_sub_dict(key, data: dict):
    return isinstance(data.get(key), dict) and data[key]
