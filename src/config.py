#!/usr/bin/env python3

import configparser
import json
import os
import threading
import time

import logger
import utils
from lib import proxy
from lib import yandex_apikey
import languages
from languages import CONFIG as LNG, YANDEX_EMOTION, YANDEX_SPEAKER


class ConfigHandler(dict):
    SETTINGS = 'settings'

    def __init__(self, cfg: dict, path: dict):
        super().__init__()
        self.update(cfg)
        self.path = path
        self._play = None  # Тут будет player, потом
        self._log = self.__print  # а тут логгер
        self._to_tts = []  # Пока player нет храним фразы тут.
        self._to_log = []  # А тут принты в лог
        self._config_init()
        self._yandex = None

    def __print(self, msg, lvl):
        self._to_log.append((msg, lvl))

    def key(self, prov, api_key):
        key_ = self.get(prov, {}).get(api_key)
        if prov == 'yandex' and not key_:
            # Будем брать ключ у транслита
            if self._yandex is None:
                self._yandex = yandex_apikey.APIKey()
            try:
                key_ = self._yandex.key
            except RuntimeError as e:
                self._log(LNG['err_ya_key'].format(e), logger.ERROR)
        return key_

    def gt(self, sec, key, default=None):
        # .get для саб-словаря
        return self.get(sec, {}).get(key, default)

    def gts(self, key, default=None):
        # .get из 'settings'
        return self['settings'].get(key, default)

    def get_uint(self, key: str, default=0) -> int:
        try:
            result = int(self.gts(key, default))
        except ValueError:
            result = 0
        else:
            if result < 0:
                result = 0
        return result

    def configure(self, log):
        self._add_log(log)
        self._print(msg='CFG: {}'.format(self))

        # ~/resources/
        self._make_dir(self.path['resources'])
        # ~/resources/models/
        self._make_dir(self.path['models'])
        # ~/resources/ding.wav ~/resources/dong.wav ~/resources/tts_error.mp3
        self._lost_file(self.path['ding'])
        self._lost_file(self.path['dong'])
        self._lost_file(self.path['tts_error'])

        self.models_load()
        self.tts_cache_check()

    def allow_connect(self, ip: str) -> bool:
        if not self['majordomo'].get('ip') and self.gts('first_love'):
            self['majordomo']['ip'] = ip
            self.config_save()
        if self.gts('last_love') and ip != self['majordomo'].get('ip'):
            return False
        return True

    def _config_init(self):
        self._cfg_check(self.config_load())
        proxy.setting(self.get('proxy', {}))

    def _cfg_check(self, to_save=False):
        for key in ['providerstt', 'providerstt']:
            val = self.gts(key)
            if val is not None:
                to_save |= self._cfg_dict_checker(val)
        to_save |= self._cfg_checker('yandex', 'emotion', YANDEX_EMOTION, 'good')
        to_save |= self._cfg_checker('yandex', 'speaker', YANDEX_SPEAKER, 'alyss')
        to_save |= self._log_file_init()
        to_save |= self._tts_cache_path_check()
        to_save |= self._first()
        if to_save:
            self.config_save()

    def _tts_cache_path_check(self):
        to_save = False
        if not self['cache']['path']:
            # ~/tts_cache/
            self['cache']['path'] = os.path.join(self.path['home'], 'tts_cache')
            to_save = True
        self._make_dir(self['cache']['path'])
        return to_save

    def _log_file_init(self):  # Выбираем доступную для записи директорию для логов
        if self['log']['file']:
            return False

        file = 'mdmterminal.log'
        for path in ('/var/log', self.path['home'], self.path['tmp']):
            target = os.path.join(path, file)
            if utils.write_permission_check(target):
                break
        self['log']['file'] = target
        return True

    def _cfg_dict_checker(self, key: str):
        if key and (key not in self or type(self[key]) != dict):
            self[key] = {}
            return True
        return False

    def _cfg_checker(self, subcfg: str, key: str, to: dict, def_: str):
        to_save = self._cfg_dict_checker(subcfg)
        if key not in self[subcfg]:
            self[subcfg][key] = def_
            to_save = True
        elif self[subcfg][key] not in to:
            self._print(LNG['err_cfg_check'].format(key, self[subcfg][key], def_), logger.ERROR)
            self[subcfg][key] = def_
            to_save = True
        return to_save

    def save_dict(self, name: str, data: dict, pretty=False) -> bool:
        file_path = os.path.join(self.path['home'], name + '.json')
        try:
            with open(file_path, 'w') as fp:
                json.dump(data, fp, ensure_ascii=False, indent=4 if pretty else None)
        except TypeError as e:
            self._print(LNG['err_save'].format(file_path, str(e)), logger.ERROR)
            return False
        return True

    def load_dict(self, name: str) -> dict or None:
        file_path = os.path.join(self.path['home'], name + '.json')
        if not os.path.isfile(file_path):
            self._print(LNG['miss_file'].format(file_path))
            return None
        try:
            with open(file_path) as fp:
                return json.load(fp)
        except (json.decoder.JSONDecodeError, TypeError) as e:
            self._print(LNG['err_load'].format(file_path, str(e)), logger.ERROR)
            return None

    def add_play(self, play):
        self._play = play
        # Произносим накопленные фразы
        for (phrase, is_info) in self._to_tts:
            self._play.say_info(phrase, lvl=0, wait=0.5) if is_info else self._play.say(phrase, lvl=0, wait=0.5)
        self._to_tts.clear()

    def _add_log(self, log):
        self._log = log
        [self._log(msg, lvl) for (msg, lvl) in self._to_log]
        self._to_log.clear()

    def config_save(self):
        wtime = time.time()

        config = configparser.ConfigParser()
        config.add_section(self.SETTINGS)
        for key, val in self.items():
            if type(val) == dict:
                config[key] = val

        with open(self.path['settings'], 'w') as configfile:
            config.write(configfile)
        self._print(LNG['save_for'].format(utils.pretty_time(time.time() - wtime)), logger.INFO)
        self._print(LNG['save'], mode=2)

    def models_load(self):
        self.path['models_list'] = []
        if not os.path.isdir(self.path['models']):
            self._print(LNG['miss_models'].format(self.path['models']), logger.INFO, 3)
            return

        count = 0
        for file in os.listdir(self.path['models']):
            full_path = os.path.join(self.path['models'], file)
            if os.path.isfile(full_path) and os.path.splitext(file)[1] in self.path['model_supports']:
                self.path['models_list'].append(full_path)
                count += 1

        self._print(LNG['models_count_call'].format(count), logger.INFO, 3)

    def config_load(self):
        wtime = time.time()
        if not os.path.isfile(self.path['settings']):
            self._print(LNG['miss_settings'].format(self.path['settings']), logger.INFO)
            return False
        updater = ConfigUpdater(self, self._print)
        count = updater.from_ini(self.path['settings'])
        wtime = time.time() - wtime
        self._lang_init()
        self._print(LNG['load_for'].format(count, utils.pretty_time(wtime)), logger.INFO)
        self._print(LNG['load'], logger.INFO, mode=2)
        return updater.save_me

    def _lang_init(self):
        lang = self.gts('lang')
        deep_check = self.gts('lang_check', 0)
        err = languages.set_lang(lang, None if not deep_check else self._print)
        if err:
            self._print(LNG['err_lng'].format(lang, err), logger.ERROR)
        self._print(LNG['lng_load_for'].format(lang, utils.pretty_time(languages.load_time())), logger.INFO)

    def json_to_cfg(self, data: str or dict) -> bool:
        updater = ConfigUpdater(self, self._print)
        return updater.from_json(data) > 0 if isinstance(data, str) else updater.from_dict(data) > 0

    def tts_cache_check(self):
        cache_path = self.gt('cache', 'path')
        if not os.path.isdir(cache_path):
            self._print(msg=LNG['miss_tts_cache'].format(cache_path), mode=3)
            return
        max_size = self['cache'].get('tts_size', 50) * 1024 * 1024
        current_size = 0
        files = []
        # Формируем список из пути и размера файлов, заодно считаем общий размер.
        for file in os.listdir(cache_path):
            pfile = os.path.join(cache_path, file)
            if os.path.isfile(pfile):
                fsize = os.path.getsize(pfile)
                current_size += fsize
                files.append([pfile, fsize])
        normal_size = not files or current_size < max_size or max_size < 0
        say = LNG['tts_cache_size'].format(
            utils.pretty_size(current_size),
            LNG['tts_cache_act_list'][0] if normal_size else LNG['tts_cache_act_list'][1]
        )
        self._print(say, logger.INFO, 1 if normal_size else 3)
        if normal_size:
            return

        new_size = int(max_size * 0.7)
        deleted_files = 0
        # Сортируем файлы по дате последнего доступа
        files.sort(key=lambda x: os.path.getatime(x[0]))
        for file in files:
            if current_size <= new_size:
                break
            current_size -= file[1]
            self._print(LNG['delete_file'].format(file[0]))
            os.remove(file[0])
            deleted_files += 1

        self._print(LNG['deleted_files'].format(deleted_files, utils.pretty_size(current_size)), logger.INFO, 3)

    def _make_dir(self, path: str):
        if not os.path.isdir(path):
            self._print(LNG['create_dir'].format(path), logger.INFO)
            os.makedirs(path)

    def _lost_file(self, path: str):
        if not os.path.isfile(path):
            self._print(LNG['miss_file_fixme'].format(path), logger.CRIT, 3)

    def _print(self, msg: str, lvl=logger.DEBUG, mode=1):  # mode 1 - print, 2 - say, 3 - both
        if mode in [1, 3]:
            self._log(msg, lvl)
        if mode in [2, 3]:
            is_info = lvl <= logger.INFO
            if self._play is None:
                self._to_tts.append((msg, is_info))
            else:
                self._play.say_info(msg, lvl=0) if is_info else self._play.say(msg, lvl=0)

    def _first(self):
        to_save = False
        if not self.gts('ip'):
            self['settings']['ip'] = utils.get_ip_address()
            to_save = True
        if not self['majordomo'].get('ip'):
            self._print(LNG['say_ip'].format(self.gts('ip')), logger.WARN, 3)
        return to_save


class ConfigUpdater:
    SETTINGS = 'settings'
    PROVIDERS_KEYS = ('providertts', 'providerstt')
    API_KEYS = ('apikeytts', 'apikeystt')
    # Автоматически переносим ключи в подсекции из settings.
    # Ключ: (новая секция, новое имя ключа)
    KEY_MOVE = {
        'ip_server': ('majordomo', 'ip'),
        'linkedroom': ('majordomo', 'linkedroom'),
    }

    def __init__(self, cfg, log):
        self._cfg = cfg
        self._log = log
        self._new_cfg = {}
        self._change_count = 0
        self._updated_count = 0
        self._lock = threading.Lock()
        self._save_me = False

    def _clear(self):
        self._new_cfg = {}
        self._change_count = 0
        self._updated_count = 0
        self._save_me = False

    def _ini_to_cfg(self, path: str):
        cfg = configparser.ConfigParser()
        cfg.read(path)
        data = {sec.lower(): dict(cfg[sec]) for sec in cfg.sections()}
        self._parser(data)

    def _json_to_cfg(self, data: str):
        try:
            data = {key.lower(): val for key, val in json.loads(data).items()}
        except (json.decoder.JSONDecodeError, TypeError) as err:
            self._log(LNG['wrong_json'].format(data, err.msg), logger.ERROR)
            return
        self._parser(self._dict_normalization(data), True)

    def _dict_normalization(self, data: dict) -> dict:
        settings = {key: data.pop(key) for key in [x for x in data.keys()] if not isinstance(data[key], dict)}
        if settings:
            if self.SETTINGS not in data:
                data[self.SETTINGS] = settings
            else:
                data[self.SETTINGS].update(settings)
        return data

    def _parser(self, data: dict, external=False):
        for key, val in data.items():
            if not isinstance(val, dict):
                self._print_result('Section must be dict. {}: {}'.format(key, val), logger.CRIT)
                continue
            if key == self.SETTINGS:
                self._settings_adapter(val)
            self._recursive_parser(self._cfg, self._new_cfg, key, val, external)

    def _recursive_parser(self, cfg: dict, cfg_diff: dict, key, val, external=False):
        if not isinstance(key, str):
            self._log(LNG['wrong_key'].format(type(key), key), logger.ERROR)
            return
        key = key if not external else key.lower()
        if isinstance(val, dict) and isinstance(cfg.get(key, {}), dict):  # секция
            self._parse_section_element(cfg, cfg_diff, key, val, external)
        elif external and isinstance(val, (dict, list, set, tuple)):
            self._log(LNG['wrong_val'].format(key, val), logger.ERROR)
        else:
            self._parse_param_element(cfg, cfg_diff, key, val, external)

    def _parse_section_element(self, cfg: dict, cfg_diff: dict, key, val, external):
        if external and key not in cfg:  # Не принимаем новые секции от сервера
            self._log(LNG['ignore_section'].format(key, val), logger.ERROR)
            return
        cfg_diff[key] = cfg_diff.get(key, {})
        for key_, val_ in val.items():
            self._recursive_parser(cfg.get(key, {}), cfg_diff[key], key_, val_, external)
        if not cfg_diff[key]:  # Удаляем пустые секции
            del cfg_diff[key]

    def _parse_param_element(self, cfg: dict, cfg_diff: dict, key, val, external):
        if external and isinstance(val, str):
            val = val.lower()
        try:
            tmp = type(cfg.get(key, ''))(val)
        except (ValueError, TypeError) as e:
            self._log(LNG['wrong_type_val'].format(key, val, type(val), cfg.get(key, 'None'), e), logger.ERROR)
        else:
            if key not in cfg or tmp != cfg[key]:
                self._change_count += 1
                cfg_diff[key] = tmp

    def _settings_adapter(self, data: dict):
        for key in [x for x in data.keys() if isinstance(x, str)]:
            for mover in (self._api_key_move, self._key_move):
                if key not in data:  # элемент мог быть удален мовером
                    break
                mover(data, key, data[key])

    def _api_key_move(self, data: dict, key: str, val):
        key = key.lower()
        if isinstance(val, str) and key in self.PROVIDERS_KEYS:
            val = val.lower()
            api_key = 'apikey{}'.format(key[-3:])  # apikeytts or apikeystt
            if api_key in data:
                if self._cfg.get(val, {}).get(api_key) != data[api_key]:
                    self._new_cfg[val] = self._new_cfg.get(val, {})
                    self._new_cfg[val][api_key] = data[api_key]
                    self._change_count += 1
                    self._save_me = True
                # Удаляем api-ключ из settings
                data.pop(api_key)

    def _key_move(self, data: dict, key: str, val):
        key_lower = key.lower()
        if key_lower in self.KEY_MOVE:
            # перемещаем ключ
            sec = self.KEY_MOVE[key_lower][0]
            key_move = self.KEY_MOVE[key_lower][1]
            if sec not in self._new_cfg:
                self._new_cfg[sec] = {}

            old_count = self._change_count
            self._parse_param_element(self._cfg.get(sec, {}), self._new_cfg[sec], key_move, val, False)
            self._save_me = self._save_me or self._change_count > old_count

            if not self._new_cfg[sec]:
                del self._new_cfg[sec]
            # Удаляем перемещенный ключ из settings
            data.pop(key)

    def _print_result(self, from_, lvl=logger.DEBUG):
        self._log('{}: \'{}\', count: {}'.format(from_, self._new_cfg, self._change_count), lvl)

    def _update(self):
        if sum([len(val) for val in self._new_cfg.values()]) > self._change_count:
            self._print_result('FIXME!', logger.CRIT)
            return 0
        self._update_recursive(self._cfg, self._new_cfg)
        if self._change_count != self._updated_count:
            self._print_result('update_count={}!=count. FIXME!'.format(self._updated_count), logger.CRIT)
            return 0
        return self._updated_count

    def _update_recursive(self, to_, from_):
        for k, v in from_.items():
            if isinstance(v, dict):
                if k not in to_:
                    to_[k] = {}
                self._update_recursive(to_[k], v)
            else:
                to_[k] = v
                self._updated_count += 1

    def from_ini(self, path: str):
        with self._lock:
            self._clear()
            self._ini_to_cfg(path)
            self._print_result('INI')
            return self._update()

    def from_json(self, json_: str):
        with self._lock:
            self._clear()
            self._json_to_cfg(json_)
            self._print_result('JSON')
            return self._update()

    def from_dict(self, dict_: dict):
        with self._lock:
            self._clear()
            self._parser(dict_)
            self._print_result('DICT')
            return self._update()

    @property
    def save_me(self):
        with self._lock:
            return self._save_me
