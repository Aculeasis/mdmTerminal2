#!/usr/bin/env python3

import configparser
import json
import os
import time
import tempfile

import logger
import utils
from lib import yandex_apikey


class ConfigHandler(dict):
    SETTINGS = 'Settings'

    def __init__(self, cfg: dict, path: dict):
        super().__init__()
        self.update(cfg)
        self.path = path
        self._say = None  # Тут будет tts, потом
        self._log = print  # а тут логгер
        self._to_tts = []  # Пока tts нет храним принты тут.
        self._config_init()
        self._yandex = None

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
        self._log = log

        self._print(msg='CFG: {}'.format(self))

        # Расширение моделей
        self.path['model_ext'] = '.pmdl'
        self.path['model_supports'] = ['.pmdl', '.umdl']

        # ~/tts_cache/
        self.path['tts_cache'] = os.path.join(self.path['home'], 'tts_cache')
        self._make_dir(self.path['tts_cache'])

        # /tmp
        self.path['tmp'] = tempfile.gettempdir()

        # ~/resources/
        self.path['resources'] = os.path.join(self.path['home'], 'resources')
        self._make_dir(self.path['resources'])

        # ~/resources/models/
        self.path['models'] = os.path.join(self.path['resources'], 'models')
        self._make_dir(self.path['models'])
        self.models_load()

        # ~/resources/ding.wav ~/resources/dong.wav ~/resources/tts_error.mp3 ~/resources/training_service.sh
        self.path['ding'] = os.path.join(self.path['resources'], 'ding.wav')  # TODO: mp3?
        self._lost_file(self.path['ding'])

        self.path['dong'] = os.path.join(self.path['resources'], 'dong.wav')
        self._lost_file(self.path['dong'])

        self.path['tts_error'] = os.path.join(self.path['resources'], 'tts_error.mp3')
        self._lost_file(self.path['tts_error'])

        self.tts_cache_check()

    def allow_connect(self, ip: str) -> bool:
        if not self['ip_server'] and self['first_love']:
            self['ip_server'] = ip
            self.config_save()
        if self['last_love'] and ip != self['ip_server']:
            return False
        return True

    def _config_init(self):
        # ~/settings.ini
        self.path['settings'] = os.path.join(self.path['home'], 'settings.ini')

        self.config_load()
        self._cfg_check()

    def _cfg_check(self):
        to_save = False
        if 'providerstt' in self:
            to_save |= self._cfg_dict_checker(self['providerstt'])
        if 'providerstt' in self:
            to_save |= self._cfg_dict_checker(self['providerstt'])
        to_save |= self._cfg_checker('yandex', 'emotion', utils.YANDEX_EMOTION, 'good')
        to_save |= self._cfg_checker('yandex', 'speaker', utils.YANDEX_SPEAKER, 'alyss')
        to_save |= self._first()
        if to_save:
            self.config_save()

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

    def join_low_say(self, low_say):
        self._say = low_say
        # Произносим накопленные фразы
        while len(self._to_tts):
            self._say(self._to_tts.pop(0), lvl=0, wait=0.5)

    def join_logger(self, log):
        self._log = log

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

    @staticmethod
    def _cfg_convert(config: configparser.ConfigParser, sec, key, oldval):
        if oldval is None:
            return config[sec][key]
        if type(oldval) == int:
            return config.getint(sec, key)
        elif type(oldval) == float:
            return config.getfloat(sec, key)
        elif type(oldval) == bool:
            return config.getboolean(sec, key)
        return config[sec][key]

    def config_load(self):
        wtime = time.time()
        if not os.path.isfile(self.path['settings']):
            self._print(
                'Файл настроек не найден по пути {}. Для первого запуска это нормально'.format(self.path['settings']),
                logger.INFO)
            return
        config = configparser.ConfigParser()
        config.read(self.path['settings'])
        count = 0
        for sec in config.sections():
            if sec != self.SETTINGS:
                self._cfg_dict_checker(sec)
            for key in config[sec]:
                count += 1
                if sec == self.SETTINGS:
                    self[key] = self._cfg_convert(config, sec, key, self.get(key, None))
                else:
                    self[sec][key] = self._cfg_convert(config, sec, key, self[sec].get(key, None))

        self._print('Загружено {} опций за {}'.format(count, utils.pretty_time(time.time() - wtime)), logger.INFO)
        self._print('Конфигурация загружена!', logger.INFO, mode=2)

    def _key_parse(self, key, val, dict_):
        is_change = False
        if isinstance(dict_.get(key), dict) and isinstance(val, dict):
            for key_, val_ in val.items():
                is_change |= self._key_parse(key_, val_, dict_[key])
        elif isinstance(val, (dict, list)):
            raise ValueError('This is {}: {}'.format(str(type(val)), key))
        else:
            tmp = type(dict_.get(key, ''))(val)
            is_change |= tmp != dict_.get(key)
            dict_[key] = tmp
        return is_change

    def json_to_cfg(self, data: str or dict) -> bool:
        if isinstance(data, str):
            try:
                data = {key.lower(): val for key, val in json.loads(data).items()}
            except (json.decoder.JSONDecodeError, TypeError) as err:
                self._print('Кривой json \'{}\': {}'.format(data, err.msg), logger.ERROR)
                return False
        return self.dict_to_cfg(data)

    def dict_to_cfg(self, data: dict) -> bool:
        self._print('JSON: {}'.format(data))
        is_change = False
        for key, val in data.items():
            if key in ['providertts', 'providerstt']:
                apikey = 'apikey{}'.format(key[-3:])  # apikeytts or apikeystt
                val = str(val).lower()  # Google -> google etc.
                if apikey in data and val:
                    is_change |= self._cfg_dict_checker(val)
                    is_change |= apikey not in self[val] or self[val][apikey] != data[apikey]
                    self[val][apikey] = data[apikey]
            if key not in ['apikeytts', 'apikeystt']:
                is_change |= self._key_parse(key, val, self)
        return is_change

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
        self._print(
            'Размер tts кэша {}: {}'.format(utils.pretty_size(current_size), 'Ок.' if normal_size else 'Удаляем...'),
            logger.INFO, 1 if normal_size else 3)
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
            if self._say is None:  # tts еще нет
                self._to_tts.append(msg)
            else:
                self._say(msg, lvl=0)

    def _first(self):
        to_save = False
        if 'ip' not in self or not self['ip']:
            self['ip'] = utils.get_ip_address()
            to_save = True
        if 'ip_server' not in self or not self['ip_server']:
            self._print('Терминал еще не настроен, мой IP адрес: {}'.format(self['ip']), logger.INFO, 3)
        return to_save
