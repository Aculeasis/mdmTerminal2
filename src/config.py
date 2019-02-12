#!/usr/bin/env python3

import configparser
import json
import os
import threading
import time

import languages
import logger
import utils
from languages import CONFIG as LNG, LANG_CODE
from lib import volume
from lib.audio_utils import APMSettings
from lib.keys_utils import Keystore
from lib.proxy import proxies
from owner import Owner


class ConfigHandler(dict):
    def __init__(self, cfg: dict, path: dict, owner: Owner):
        super().__init__()
        self._plugins_api = cfg['system'].pop('PLUGINS_API', 0)
        self.update(cfg)
        self.path = path
        self.__owner = owner
        self.own = None
        self._log = self.__print  # Тут будет логгер
        self._to_tts = []  # Пока player нет храним фразы тут.
        self._to_log = []  # А тут принты в лог
        self._config_init()

    @property
    def API(self):
        return self._plugins_api

    def __print(self, msg, lvl):
        self._to_log.append((msg, lvl))

    def key(self, prov, api_key):
        if prov == 'aws':
            return self._aws_credentials()
        key_ = self.gt(prov, api_key)
        if prov == 'azure':
            return Keystore().azure(key_, self.gt('azure', 'region'))
        api = self.yandex_api(prov)
        if api == 2 or (prov == 'yandex' and not key_):
            # Будем брать ключ у транслита для старой версии
            # и (folderId, aim) для новой через oauth
            try:
                key_ = Keystore().yandex(key_, api)
            except RuntimeError as e:
                raise RuntimeError(LNG['err_ya_key'].format(e))
        return key_

    def _aws_credentials(self):
        return (
            (self.gt('aws', 'access_key_id'), self.gt('aws', 'secret_access_key'), self.gt('aws', 'region')),
            self.gt('aws', 'boto3')
        )

    @staticmethod
    def language_name() -> str:
        return languages.set_lang.language_name

    @staticmethod
    def tts_lang(provider: str) -> str:
        if provider == 'google':
            return LANG_CODE['ISO']
        elif provider == 'aws':
            return LANG_CODE['aws']
        else:
            return LANG_CODE['IETF']

    def yandex_api(self, prov):
        if prov == 'yandex':
            return self.gt(prov, 'api', 1)
        else:
            return 1

    def model_info_by_id(self, model: int):
        model -= 1
        if model < len(self.path['models_list']):
            model_name = os.path.split(self.path['models_list'][model])[1]
            phrase = self.gt('models', model_name, '')
            msg = '' if not phrase else ': "{}"'.format(phrase)
        else:
            model_name = str(model)
            phrase = ''
            msg = ': "model id out of range: {} > {}"'.format(model, len(self.path['models_list']) - 1)
        return model_name, phrase, msg

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
        self.apm_configure()

        # ~/resources/
        self._make_dir(self.path['resources'])
        # ~/data/
        self._make_dir(self.path['data'])
        # ~/plugins/
        self._make_dir(self.path['plugins'])
        # ~/resources/models/
        self._make_dir(self.path['models'])
        # ~/resources/ding.wav ~/resources/dong.wav ~/resources/tts_error.mp3
        self._lost_file(self.path['ding'])
        self._lost_file(self.path['dong'])
        self._lost_file(self.path['tts_error'])

        self.models_load()
        self.tts_cache_check()

    def allow_connect(self, ip: str) -> bool:
        if ip == '127.0.0.1':
            return True
        if not self['majordomo'].get('ip') and self.gts('first_love'):
            self['majordomo']['ip'] = ip
            self.config_save()
        if self.gts('last_love') and ip != self['majordomo'].get('ip'):
            return False
        return True

    def is_model_name(self, filename: str) -> bool:
        if not (filename and isinstance(filename, str) and not filename.startswith(('.', '~'))):
            return False
        # check wrong chars
        wrong_chars = '*/:?"|+<>\n\r\t\n\0\\'
        valid = not set(wrong_chars).intersection(filename)
        return valid and os.path.splitext(filename)[-1].lower() in self.path['model_supports']

    def _config_init(self):
        self._cfg_check(self.config_load())
        self.proxies_init()

    def proxies_init(self):
        proxies.configure(self.get('proxy', {}))

    def apm_configure(self):
        apm = APMSettings()
        apm.cfg(**self['noise_suppression'])
        if apm.failed:
            self._print(apm.failed, logger.CRIT)

    def _cfg_check(self, to_save=False):
        for key in ['providerstt', 'providerstt']:
            to_save |= self._cfg_dict_checker(self.gts(key))
        to_save |= self._log_file_init()
        to_save |= self._tts_cache_path_check()
        to_save |= self._init_volume()
        to_save |= self._first()
        if to_save:
            self.config_save()

    def _init_volume(self):
        if self.gt('volume', 'line_out'):
            return False
        self['volume']['card'], self['volume']['line_out'] = volume.extract_volume_control()
        return len(self['volume']['line_out']) > 0

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

    def get_allow_models(self) -> list:
        return utils.str_to_list(self.gt('models', 'allow'))

    def get_all_models(self) -> list:
        return [file for file in os.listdir(self.path['models']) if self.is_model_name(file)]

    def save_dict(self, name: str, data: dict, pretty=False) -> bool:
        file_path = os.path.join(self.path['data'], name + '.json')
        try:
            with open(file_path, 'w') as fp:
                json.dump(data, fp, ensure_ascii=False, indent=4 if pretty else None)
        except TypeError as e:
            self._print(LNG['err_save'].format(file_path, str(e)), logger.ERROR)
            return False
        return True

    def load_dict(self, name: str) -> dict or None:
        file_path = os.path.join(self.path['data'], name + '.json')
        if not os.path.isfile(file_path):
            self._print(LNG['miss_file'].format(file_path))
            return None
        try:
            with open(file_path) as fp:
                return json.load(fp)
        except (json.decoder.JSONDecodeError, TypeError) as e:
            self._print(LNG['err_load'].format(file_path, str(e)), logger.ERROR)
            return None

    def start(self):
        self.own = self.__owner
        # Произносим накопленные фразы
        for (phrase, is_info) in self._to_tts:
            if is_info:
                self.own.say_info(phrase, lvl=0, wait=0.5)
            else:
                self.own.say(phrase, lvl=0, wait=0.5)
        self._to_tts.clear()

    def _add_log(self, log):
        self._log = log
        [self._log(msg, lvl) for (msg, lvl) in self._to_log]
        self._to_log.clear()

    def config_save(self):
        wtime = time.time()

        config = ConfigParserOnOff()
        for key, val in self.items():
            if isinstance(val, dict):
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
        allow = self.get_allow_models()
        for file in self.get_all_models():
            full_path = os.path.join(self.path['models'], file)
            if os.path.isfile(full_path):
                if not allow or file in allow:
                    self.path['models_list'].append(full_path)
                    count += 1

        self._print(LNG['models_count_call'].format(count), logger.INFO, 3)

    def config_load(self):
        wtime = time.time()
        if not os.path.isfile(self.path['settings']):
            self._print(LNG['miss_settings'].format(self.path['settings']), logger.INFO)
            return True
        updater = ConfigUpdater(self, self._print)
        count = updater.from_ini(self.path['settings'])
        wtime = time.time() - wtime
        self.lang_init()
        self._print(LNG['load_for'].format(count, utils.pretty_time(wtime)), logger.INFO)
        self._print(LNG['load'], logger.INFO, mode=2)
        return updater.save_ini

    def lang_init(self):
        lang = self.gts('lang')
        deep_check = self.gts('lang_check')
        err = languages.set_lang(lang, None if not deep_check else self._print)
        if err:
            self._print(LNG['err_lng'].format(lang, err), logger.ERROR)
        self._print(LNG['lng_load_for'].format(lang, utils.pretty_time(languages.set_lang.load_time)), logger.INFO)

    def update_from_external(self, data: str or dict) -> dict or None:
        cu = ConfigUpdater(self, self._print)
        if isinstance(data, str):
            result = cu.from_json(data)
        elif isinstance(data, dict):
            result = cu.from_external_dict(data)
        else:
            self._print('Unknown settings type: {}'.format(type(data)), logger.ERROR)
            return None
        if result:
            return cu.diff
        else:
            return None

    def update_from_json(self, data: str or dict) -> dict or None:
        # TODO: Deprecated
        return self.update_from_external(data)

    def print_cfg_change(self):
        self._print(LNG['cfg_up'])

    def print_cfg_no_change(self):
        self._print(LNG['cfg_no_change'])

    def update_from_dict(self, data: dict) -> bool:
        return self._cfg_update(ConfigUpdater(self, self._print).from_dict(data))

    def _cfg_update(self, result: int):
        if result:
            self.config_save()
            return True
        return False

    def tts_cache_check(self):
        min_file_size = 1024
        max_size = self['cache'].get('tts_size', 50) * 1024 * 1024
        cache_path = self.gt('cache', 'path')
        if not os.path.isdir(cache_path):
            self._print(msg=LNG['miss_tts_cache'].format(cache_path), mode=3)
            return
        current_size = 0
        files, wrong_files = [], []
        # Формируем список из пути и размера файлов, заодно считаем общий размер.
        # Файлы по 1 KiB считаем поврежденными и удалим в любом случае
        for file in os.listdir(cache_path):
            pfile = os.path.join(cache_path, file)
            if os.path.isfile(pfile):
                fsize = os.path.getsize(pfile)
                if fsize > min_file_size:
                    current_size += fsize
                    files.append([pfile, fsize])
                else:
                    wrong_files.append(pfile)

        # Удаляем поврежденные файлы
        if wrong_files:
            for file in wrong_files:
                os.remove(file)
            wrong_files = [os.path.split(file)[1] for file in wrong_files]
            self._print(LNG['delete_wrong_files'].format(', '.join(wrong_files)), logger.WARN)

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
        deleted = []
        for file in files:
            if current_size <= new_size:
                break
            current_size -= file[1]
            os.remove(file[0])
            deleted_files += 1
            deleted.append(os.path.split(file[0])[1])
        self._print(LNG['delete_files'].format(', '.join(deleted)))
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
            if self.own is None:
                self._to_tts.append((msg, is_info))
            else:
                if is_info:
                    self.own.say_info(msg, lvl=0)
                else:
                    self.own.say(msg, lvl=0)

    def _first(self):
        to_save = False
        if not self.gts('ip'):
            self['settings']['ip'] = utils.get_ip_address()
            to_save = True
        if not self['majordomo'].get('ip'):
            self._print(LNG['say_ip'].format(self.gts('ip')), logger.WARN, 3)
        return to_save

    def _cfg_as_tuple(self, data: dict) -> tuple:
        result = []
        for key, val in data.items():
            if not isinstance(key, str):
                continue
            elif isinstance(val, dict):
                result.append((key, self._cfg_as_tuple(val)))
            elif isinstance(val, (bool, str, int, float, bytes)) or val is None:
                result.append((key, val))
        result.sort()
        return tuple(result)

    def __hash__(self):
        return hash(self._cfg_as_tuple(self))


class ConfigUpdater:
    SETTINGS = 'settings'
    PROVIDERS_KEYS = ('providertts', 'providerstt')
    # Не переводим значение ключей в нижний регистр даже если они от сервера в json
    NOT_LOWER = {
        'apikeytts', 'apikeystt',
        'speaker',
        'access_key_id', 'secret_access_key',
        'object_name', 'object_method', 'terminal', 'username', 'password'
    }
    # Автоматически переносим ключи от сервера, в json, в подсекции из settings.
    # Ключ: (новая секция, новое имя ключа (пустое - без изменений))
    KEY_FROM_SERVER_MOVE = {
        'ip_server': ('majordomo', 'ip'),
        'token': ('snowboy', ''),
        'clear_models': ('snowboy', ''),
    }
    EXTERNALS = (2, 3)

    def __init__(self, cfg, log):
        self._cfg = cfg
        self._log = log
        self._new_cfg = {}
        self._change_count = 0
        self._updated_count = 0
        self._lock = threading.Lock()
        self._save_me = False
        # 0 - dict, 1 - ini, 2 - server json, 3 - server dict
        self._source = None

    def _init(self, source):
        self._source = source
        self._new_cfg = {}
        self._change_count = 0
        self._updated_count = 0
        self._save_me = False

    def _ini_version_updated(self, data: dict) -> bool:
        if self._source == 1:
            try:
                file_ver = int(data['system'].pop('ini_version'))
            except (ValueError, TypeError, KeyError):
                file_ver = 0
            try:
                cfg_ver = int(self._cfg['system'].get('ini_version'))
            except (ValueError, TypeError, KeyError):
                pass
            else:
                return cfg_ver > file_ver
        return False

    def _ini_to_cfg(self, path: str):
        cfg = configparser.ConfigParser()
        cfg.read(path)
        data = {sec.lower(): dict(cfg[sec]) for sec in cfg.sections()}
        self._parser(data)

    def _json_to_cfg(self, data: str):
        try:
            data = {key.lower(): val for key, val in json.loads(data).items()}
        except (json.decoder.JSONDecodeError, TypeError, AttributeError) as err:
            self._log('Invalid json {}: {}'.format(repr(data), err), logger.ERROR)
            return
        self._parser(self._voice_assistant_mapping(data))

    def _voice_assistant_mapping(self, data: dict) -> dict:
        """
        Преобразуем [section_key] в [section][key], только если секция существует в основном конфиге.
        Также перемешаем все ключи без секции в settings.
        """
        # Если [settings] существует, он должен быть словарем
        if not isinstance(data.get(self.SETTINGS, {}), dict):
            del data[self.SETTINGS]

        # Странные параметры
        # volume_line_out определяется автоматически, а в ассистенте его даже не настроить.
        for key in ('id', 'version', 'id_terminal', 'volume_line_out'):
            data.pop(key, None)
        remove_this = []
        # Все существующие секции
        sections = {key for key in self._cfg if isinstance(self._cfg[key], dict)}
        for key in [key for key in data if isinstance(key, str) and not isinstance(data[key], dict)]:
            try:
                section, new_key = key.split('_', 1)
            except ValueError:
                continue
            section = section.replace('0', '-')
            if not new_key or not section or section not in sections:
                continue
            if not isinstance(data.get(section, {}), dict):
                self._log('Conflict found, section and key name match: \'{}\''.format(section), logger.ERROR)
                continue

            remove_this.append(key)
            if data[key] is None:
                self._log('Ignore \'NoneType\'. Key: {}'.format(key), logger.WARN)
                continue

            data[section] = data.get(section, {})
            data[section][new_key] = data[key]

            # Удаляем конфликтный мусор
            if new_key in data:
                remove_this.append(new_key)

        for key in remove_this:
            data.pop(key, None)

        # Перемещаем ключи в settings
        settings = {key: data.pop(key) for key in [x for x in data.keys()] if not isinstance(data[key], dict)}
        if settings:
            data[self.SETTINGS] = data.get(self.SETTINGS, {})
            data[self.SETTINGS].update(settings)
        return data

    def _parser(self, data: dict):
        self._save_me |= self._ini_version_updated(data)
        self._settings_adapter(data)
        for key, val in data.items():
            if not isinstance(val, dict):
                self._print_result('Section must be dict. {}: {}'.format(key, val), logger.CRIT)
                continue
            self._recursive_parser(self._cfg, self._new_cfg, key, val, self._source in self.EXTERNALS)

    def _recursive_parser(self, cfg: dict, cfg_diff: dict, key, val, external):
        if not isinstance(key, str):
            self._log('Key type must be string only, not {}. Ignore key \'{}\''.format(type(key), key), logger.ERROR)
            return
        key = key if not external else key.lower()
        if isinstance(val, dict) and isinstance(cfg.get(key, {}), dict):  # секция
            self._parse_section_element(cfg, cfg_diff, key, val, external)
        elif external and isinstance(val, (dict, list, set, tuple)):
            msg = 'Invalid type of option \'{}:{}\' {}, from server. Ignoring.'.format(key, val, type(val))
            self._log(msg, logger.ERROR)
        else:
            if self._parse_param_element(cfg, cfg_diff, key, val, self._source == 2):
                self._change_count += 1

    def _parse_section_element(self, cfg: dict, cfg_diff: dict, key, val, external):
        if external and key not in cfg:  # Не принимаем новые секции от сервера
            self._log('Ignore new section from server \'{}:{}\''.format(key, val), logger.ERROR)
            return
        cfg_diff[key] = cfg_diff.get(key, {})
        for key_, val_ in val.items():
            self._recursive_parser(cfg.get(key, {}), cfg_diff[key], key_, val_, external)
        if not cfg_diff[key] and key in cfg:  # Удаляем существующие пустые секции
            del cfg_diff[key]

    def _parse_param_element(self, cfg: dict, cfg_diff: dict, key, val, from_json):
        if from_json and isinstance(val, str) and key not in self.NOT_LOWER:
            val = val.lower()
        source_type = type(cfg.get(key, ''))
        try:
            if val is None and self._source == 2:
                # ignore None (null) from server
                raise ValueError('Ignore \'NoneType\'')
            tmp = source_type(val) if source_type != bool else utils.bool_cast(val)
        except (ValueError, TypeError) as e:
            msg = 'Wrong type of option \'{}:{}\' {}, keep old value. {}'.format(key, val, type(val), e)
            self._log(msg, logger.ERROR)
        else:
            if key not in cfg or tmp != cfg[key]:
                cfg_diff[key] = tmp
                return True
        return False

    def _settings_adapter(self, cfg: dict):
        if not (self.SETTINGS in cfg and isinstance(cfg[self.SETTINGS], dict) and self._source):
            return
        data = cfg[self.SETTINGS]
        for key in [x for x in data.keys() if isinstance(x, str)]:
            for mover in (self._api_key_move, self._key_move_server):
                if key not in data:  # элемент мог быть удален мовером
                    break
                mover(data, key, data[key], cfg)

    def _api_key_move(self, data: dict, key: str, val, cfg: dict):
        key = key.lower()
        if isinstance(val, str) and key in self.PROVIDERS_KEYS:
            val = val.lower()
            if not val:
                val = 'unset'
            api_key = 'apikey{}'.format(key[-3:])  # apikeytts or apikeystt
            if api_key in data:
                if cfg.get(val, {}).get(api_key) != data[api_key]:
                    if not isinstance(self._cfg.get(val), dict):
                        self._cfg[val] = {}
                    cfg[val] = cfg.get(val, {})
                    cfg[val][api_key] = data[api_key]
                    self._save_me = True
                # Удаляем api-ключ из settings
                data.pop(api_key)

    def _key_move_server(self, data: dict, key: str, val, cfg: dict):
        if self._source == 2:
            self._key_move_from(data, key, val, self.KEY_FROM_SERVER_MOVE, cfg)

    def _key_move_from(self, data: dict, key: str, val, rules: dict, cfg: dict):
        key_lower = key.lower()
        if key_lower in rules:
            # перемещаем ключ
            sec = rules[key_lower][0]
            key_move = rules[key_lower][1] or key_lower
            add_empty = False
            if sec not in cfg:
                cfg[sec] = {}
                add_empty = True

            self._save_me |= self._parse_param_element(cfg.get(sec, {}), cfg[sec], key_move, val, False)

            if not cfg[sec] and add_empty:
                del cfg[sec]
            elif add_empty and sec not in self._cfg:
                self._cfg[sec] = {}
            # Удаляем перемещенный ключ из settings
            data.pop(key)

    def _print_result(self, from_, lvl=logger.DEBUG):
        self._log('{}: \'{}\', count: {}'.format(from_, utils.mask_cfg(self._new_cfg), self._change_count), lvl)

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
            self._init(1)
            self._ini_to_cfg(path)
            self._print_result('INI')
            return self._update()

    def from_json(self, json_: str):
        with self._lock:
            self._init(2)
            self._json_to_cfg(json_)
            self._print_result('JSON')
            return self._update()

    def from_dict(self, dict_: dict):
        with self._lock:
            self._init(0)
            self._parser(dict_)
            self._print_result('DICT')
            return self._update()

    def from_external_dict(self, dict_: dict):
        with self._lock:
            self._init(3)
            self._parser(dict_)
            self._print_result('extDICT')
            return self._update()

    @property
    def save_ini(self):
        with self._lock:
            return self._save_me

    @property
    def diff(self):
        return self._new_cfg


class ConfigParserOnOff(configparser.ConfigParser):
    """bool (True/False) -> (on/off)"""
    def read_dict(self, dictionary, source='<dict>'):
        """Read configuration from a dictionary.

        Keys are section names, values are dictionaries with keys and values
        that should be present in the section. If the used dictionary type
        preserves order, sections and their keys will be added in order.

        All types held in the dictionary are converted to strings during
        reading, including section names, option names and keys.

        Optional second argument is the `source' specifying the name of the
        dictionary being read.
        """
        elements_added = set()
        for section, keys in dictionary.items():
            section = str(section)
            try:
                self.add_section(section)
            except (configparser.DuplicateSectionError, ValueError):
                if self._strict and section in elements_added:
                    raise
            elements_added.add(section)
            for key, value in keys.items():
                key = self.optionxform(str(key))
                if value is not None:
                    if isinstance(value, bool):
                        value = 'on' if value else 'off'
                    else:
                        value = str(value)
                if self._strict and (section, key) in elements_added:
                    raise configparser.DuplicateOptionError(section, key, source)
                elements_added.add((section, key))
                self.set(section, key, value)
