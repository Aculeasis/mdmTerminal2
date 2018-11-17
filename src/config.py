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


class ConfigHandler(dict):
    SETTINGS = 'Settings'

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
                self._log('Ошибка получения ключа для Yandex: {}'.format(e), logger.ERROR)
        return key_

    def get_uint(self, key: str, default=0) -> int:
        try:
            result = int(self.get(key, default))
        except ValueError:
            result = 0
        else:
            if result < 0:
                result = 0
        return result

    def configure(self, log):
        self._add_log(log)
        self._print(msg='CFG: {}'.format(self))

        # ~/tts_cache/
        self._make_dir(self.path['tts_cache'])
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
        if not self['ip_server'] and self['first_love']:
            self['ip_server'] = ip
            self.config_save()
        if self['last_love'] and ip != self['ip_server']:
            return False
        return True

    def _config_init(self):
        self._cfg_check(self.config_load())
        proxy.setting(self.get('proxy', {}))

    def _cfg_check(self, to_save=False):
        for key in ['providerstt', 'providerstt']:
            if key in self:
                to_save |= self._cfg_dict_checker(self[key])
        to_save |= self._cfg_checker('yandex', 'emotion', utils.YANDEX_EMOTION, 'good')
        to_save |= self._cfg_checker('yandex', 'speaker', utils.YANDEX_SPEAKER, 'alyss')
        to_save |= self._log_file_init()
        to_save |= self._first()
        if to_save:
            self.config_save()

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
            self._print('Ошибка в конфиге, {} не может быть {}. Установлено: {}'.format(key, self[subcfg][key], def_),
                        logger.ERROR
                        )
            self[subcfg][key] = def_
            to_save = True
        return to_save

    def save_dict(self, name: str, data: dict) -> bool:
        file_path = os.path.join(self.path['home'], name + '.json')
        try:
            with open(file_path, 'w') as fp:
                json.dump(data, fp, ensure_ascii=False)
        except TypeError as e:
            self._print('Ошибка сохранения {}: {}'.format(file_path, str(e)), logger.ERROR)
            return False
        return True

    def load_dict(self, name: str) -> dict or None:
        file_path = os.path.join(self.path['home'], name + '.json')
        if not os.path.isfile(file_path):
            self._print('Файл не найден: {}'.format(file_path))
            return None
        try:
            with open(file_path) as fp:
                return json.load(fp)
        except (json.decoder.JSONDecodeError, TypeError) as e:
            self._print('Ошибка загрузки {}: {}'.format(file_path, str(e)), logger.ERROR)
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
            else:
                config.set(self.SETTINGS, key, str(val))

        with open(self.path['settings'], 'w') as configfile:
            config.write(configfile)
        self._print('Конфигурация сохранена за {}'.format(utils.pretty_time(time.time() - wtime)), logger.INFO)
        self._print('Конфигурация сохранена!', mode=2)

    def models_load(self):
        self.path['models_list'] = []
        if not os.path.isdir(self.path['models']):
            self._print('Директория с моделями не найдена {}'.format(self.path['models']), logger.INFO, 3)
            return

        count = 0
        for file in os.listdir(self.path['models']):
            full_path = os.path.join(self.path['models'], file)
            if os.path.isfile(full_path) and os.path.splitext(file)[1] in self.path['model_supports']:
                self.path['models_list'].append(full_path)
                count += 1

        if count == 1:
            et = 'ь'
        elif count in [2, 3, 4]:
            et = 'и'
        else:
            et = 'ей'
        pretty = ['ноль', 'одна', 'две', 'три', 'четыре', 'пять', 'шесть']
        count = pretty[count] if count < 7 else count
        self._print('Загружено {} модел{}'.format(count, et), logger.INFO, 3)

    def config_load(self):
        wtime = time.time()
        if not os.path.isfile(self.path['settings']):
            self._print(
                'Файл настроек не найден по пути {}. Для первого запуска это нормально'.format(self.path['settings']),
                logger.INFO)
            return False
        updater = ConfigUpdater(self, self._print)
        count = updater.from_ini(self.path['settings'])
        self._print('Загружено {} опций за {}'.format(count, utils.pretty_time(time.time() - wtime)), logger.INFO)
        self._print('Конфигурация загружена!', logger.INFO, mode=2)
        return updater.save_me

    def json_to_cfg(self, data: str or dict) -> bool:
        updater = ConfigUpdater(self, self._print)
        return updater.from_json(data) > 0 if isinstance(data, str) else updater.from_dict(data) > 0

    def tts_cache_check(self):
        if not os.path.isdir(self.path['tts_cache']):
            self._print(msg='Директория c tts кэшем не найдена {}'.format(self.path['tts_cache']), mode=3)
            return
        max_size = self['cache'].get('tts_size', 50) * 1024 * 1024
        current_size = 0
        files = []
        # Формируем список из пути и размера файлов, заодно считаем общий размер.
        for file in os.listdir(self.path['tts_cache']):
            pfile = os.path.join(self.path['tts_cache'], file)
            if os.path.isfile(pfile):
                fsize = os.path.getsize(pfile)
                current_size += fsize
                files.append([pfile, fsize])
        normal_size = not files or current_size < max_size or max_size < 0
        say = 'Размер tts кэша {}: {}'.format(utils.pretty_size(current_size), 'Ок.' if normal_size else 'Удаляем...')
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
            self._print('Удаляю {}'.format(file[0]))
            os.remove(file[0])
            deleted_files += 1

        self._print('Удалено {} файлов. Новый размер TTS кэша {}.'.format(
            deleted_files, utils.pretty_size(current_size)), logger.INFO, 3
        )

    def _make_dir(self, path: str):
        if not os.path.isdir(path):
            self._print('Директория {} не найдена. Создаю...'.format(path), logger.INFO)
            os.makedirs(path)

    def _lost_file(self, path: str):
        if not os.path.isfile(path):
            self._print('Файл {} не найден. Это надо исправить!'.format(path), logger.CRIT, 3)

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
        if 'ip' not in self or not self['ip']:
            self['ip'] = utils.get_ip_address()
            to_save = True
        if 'ip_server' not in self or not self['ip_server']:
            self._print('Терминал еще не настроен, мой IP адрес: {}'.format(self['ip']), logger.WARN, 3)
        return to_save


class ConfigUpdater:
    SETTINGS = 'settings'
    PROVIDERS_KEYS = ('providertts', 'providerstt')
    API_KEYS = ('apikeytts', 'apikeystt')

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
        data = {}
        for sec in cfg.sections():
            d_sec = sec if sec.lower() != self.SETTINGS else self.SETTINGS
            data[d_sec] = {key: cfg.get(sec, key) for key in cfg[sec]}
        self._parser(self._dict_normalization(data), key_cast=True)

    def _json_to_cfg(self, data: str):
        try:
            data = {key.lower(): val for key, val in json.loads(data).items()}
        except (json.decoder.JSONDecodeError, TypeError) as err:
            self._log('Кривой json \'{}\': {}'.format(data, err.msg), logger.ERROR)
            return
        self._parser(self._dict_normalization(data), True)

    def _recursive_parser(self, cfg: dict, cfg_diff: dict, key, val, external, first=False):
        if not isinstance(key, str):
            msg = 'Ключи настроек могут быть только строками, не {}. Игнорирую ключ \'{}\''
            self._log(msg.format(type(key), key), logger.ERROR)
            return
        key = key if not external else key.lower()
        if isinstance(val, dict) and isinstance(cfg.get(key, {}), dict):  # секция
            self._parse_section_element(cfg, cfg_diff, key, val, external)
        elif isinstance(val, (dict, list, set, tuple)):
            msg = 'Недопустимое значение \'{}:{}\'. Игнорирую'
            self._log(msg.format(key, val), logger.ERROR)
        elif not (first and key in self.API_KEYS):
            if external and isinstance(val, str):
                val = val.lower()
            self._parse_param_element(cfg, cfg_diff, key, val)

    def _parse_section_element(self, cfg: dict, cfg_diff: dict, key, val, external):
        if external and key not in cfg:  # Не принимаем новые секции от сервера
            msg = 'Игнорируем неизвестную секцию от сервера \'{}:{}\''
            self._log(msg.format(key, val), logger.ERROR)
            return
        cfg_diff[key] = cfg_diff.get(key, {})
        for key_, val_ in val.items():
            self._recursive_parser(cfg.get(key, {}), cfg_diff[key], key_, val_, external)
        if not cfg_diff[key]:  # Удаляем пустые секции
            del cfg_diff[key]

    def _parse_param_element(self, cfg: dict, cfg_diff: dict, key, val):
        try:
            tmp = type(cfg.get(key, ''))(val)
        except (ValueError, TypeError) as e:
            msg = 'Не верный тип настройки \'{}:{}\' {}. Сохраняем старое значение: \'{}\'. {}'
            self._log(msg.format(key, val, type(val), cfg.get(key, 'None'), e), logger.ERROR)
        else:
            if key not in cfg or tmp != cfg[key]:
                self._change_count += 1
                cfg_diff[key] = tmp

    def _api_key_cast(self, data, key, val):
        if not isinstance(key, str):
            return
        key = key.lower()
        if key in self.PROVIDERS_KEYS and isinstance(val, str):
            val = val.lower()
            api_key = 'apikey{}'.format(key[-3:])  # apikeytts or apikeystt
            if api_key in data and self._cfg.get(val, {}).get(api_key) != data[api_key]:
                self._new_cfg[val] = self._new_cfg.get(val, {})
                self._new_cfg[val][api_key] = data[api_key]
                self._change_count += 1
                self._save_me = True

    def _parser(self, data: dict, external=False, key_cast=False):
        key_cast = key_cast or external
        for key, val in data.items():
            if key_cast:
                self._api_key_cast(data, key, val)
            self._recursive_parser(self._cfg, self._new_cfg, key, val, external, True)

    def _dict_normalization(self, data: dict) -> dict:
        if isinstance(data.get(self.SETTINGS, {}), dict):
            data.update(data.pop(self.SETTINGS, {}))
        else:
            data.pop(self.SETTINGS, None)
        return data

    def _print_result(self, from_, lvl=logger.DEBUG):
        self._log('{}: \'{}\', count: {}'.format(from_, self._new_cfg, self._change_count), lvl)

    def _update(self):
        if len(self._new_cfg) > self._change_count:
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
