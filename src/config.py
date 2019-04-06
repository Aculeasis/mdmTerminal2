#!/usr/bin/env python3

import configparser
import os
import platform
import shutil
import time

import languages
import logger
import utils
from languages import CONFIG as LNG, LANG_CODE
from lib import volume
from lib.audio_utils import APMSettings
from lib.ip_storage import make_interface_storage
from lib.keys_utils import Keystore
from lib.map_settings.wiki_parser import WikiParser
from lib.proxy import proxies
from lib.tools.config_updater import ConfigUpdater
from owner import Owner

DATA_FORMATS = {'json': '.json', 'yaml': '.yml'}


class DummyOwner:
    def __init__(self):
        self._info = []
        self._say = []

    def say(self, msg: str, lvl: int = 0, alarm=None, wait=0, is_file: bool = False, blocking: int = 0):
        self._say.append((msg, lvl, alarm, wait, is_file, blocking))

    def say_info(self, msg: str, lvl: int = 0, alarm=None, wait=0, is_file: bool = False):
        self._info.append((msg, lvl, alarm, wait, is_file))

    def replacement(self, own: Owner):
        # Произносим накопленные фразы
        for info in self._info:
            own.say_info(*info)
        for say in self._say:
            own.say(*say)


class ConfigHandler(dict):
    def __init__(self, cfg: dict, path: dict, log, owner: Owner):
        super().__init__()
        self._start_time = time.time()
        self._plugins_api = cfg['system'].pop('PLUGINS_API', 0)
        self._version_info = cfg['system'].pop('VERSION', (0, 0, 0))
        self.platform = platform.system().capitalize()
        self.detector = 'snowboy' if self.platform == 'Linux' else None
        self._save_me_later = False
        self._allow_addresses = []
        self.update(cfg)
        self.path = path
        self.__owner = owner
        self.own = DummyOwner()  # Пока player нет храним фразы тут.
        self.log = log
        self._config_init()

    @property
    def uptime(self) -> int:
        return int(time.time() - self._start_time)

    @property
    def API(self):
        return self._plugins_api

    @property
    def version_info(self) -> tuple:
        return self._version_info

    @property
    def version_str(self) -> str:
        return '.'.join(str(x) for x in self._version_info)

    @property
    def wiki_desc(self) -> dict:
        return WikiParser(self, self.log.add('Wiki')).get()

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

    def _path_check(self):
        for dir_ in ('resources', 'data', 'plugins', 'models', 'samples'):
            self._make_dir(self.path[dir_])
        for file in ('ding', 'dong', 'bimp'):
            self._lost_file(self.path[file])

    def _porcupine_switcher(self):
        try:
            if not utils.porcupine_check(self.path['home']):
                return
        except RuntimeError as e:
            self.log('Porcupine broken: {}'.format(e), logger.WARN)
            return

        self.path['model_ext'] = '.ppn'
        self.path['model_supports'].clear()
        self.path['model_supports'].append(self.path['model_ext'])
        self.detector = 'porcupine'
        self.log('Change detector to Porcupine', logger.INFO)

    def allow_connect(self, ip: str) -> bool:
        if ip not in self._allow_addresses:
            return False
        if ip == '127.0.0.1':
            return True
        if not self['smarthome'].get('ip') and self.gts('first_love'):
            self['smarthome']['ip'] = ip
            self.config_save()
        if self.gts('last_love') and ip != self['smarthome'].get('ip'):
            return False
        return True

    def is_model_name(self, filename: str) -> bool:
        if not (filename and isinstance(filename, str) and not filename.startswith(('.', '~'))):
            return False
        # check wrong chars
        wrong_chars = '*/:?"|+<>\n\r\t\n\0\\'
        valid = not set(wrong_chars).intersection(filename)
        return valid and os.path.splitext(filename)[-1].lower() in self.path['model_supports']

    def path_to_sample(self, model_id: str, sample_num) -> str:
        return os.path.join(self.path['samples'], model_id, '{}.wav'.format(sample_num))

    def remove_samples(self, model_id: str):
        if not model_id:
            raise RuntimeError('model_id empty')
        target = os.path.join(self.path['samples'], model_id)
        if not os.path.isdir(target):
            raise RuntimeError('{} not a directory'.format(target))
        try:
            shutil.rmtree(target)
        except Exception as e:
            raise RuntimeError(e)

    def _config_init(self):
        self._cfg_check(self.config_load())
        self._path_check()
        self.tts_cache_check()

        self.proxies_init()
        self.apm_configure()
        self._porcupine_switcher()

        self.models_load()
        self.allow_addresses_init()
        self._say_ip()

    def allow_addresses_init(self):
        ips = self['smarthome']['allow_addresses']
        try:
            self._allow_addresses = make_interface_storage(ips)
            msg = str(self._allow_addresses)
        except RuntimeError as e:
            self._allow_addresses = []
            msg = 'NONE'
            wrong = '[smarthome] allow_addresse = {}'.format(ips)
            self.log('Wrong value {}: {}'.format(repr(wrong), e), logger.WARN)
        self.log('Allow IP addresses: {}'.format(msg), logger.INFO)

    def proxies_init(self):
        proxies.configure(self.get('proxy', {}))

    def apm_configure(self):
        apm = APMSettings()
        apm.cfg(**self['noise_suppression'])
        if apm.failed:
            self.log(apm.failed, logger.CRIT)

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

    def save_dict(self, name: str, data: dict, pretty=False, format_='json') -> bool:
        file_path = os.path.join(self.path['data'], name + DATA_FORMATS.get(format_, '.json'))
        try:
            utils.dict_to_file(file_path, data, pretty)
        except RuntimeError as e:
            self.log(LNG['err_save'].format(file_path, str(e)), logger.ERROR)
            return False
        return True

    def load_dict(self, name: str, format_='json') -> dict or None:
        file_path = os.path.join(self.path['data'], name + DATA_FORMATS.get(format_, '.json'))
        if not os.path.isfile(file_path):
            self.log(LNG['miss_file'].format(file_path))
            return None
        try:
            return utils.dict_from_file(file_path)
        except RuntimeError as e:
            self.log(LNG['err_load'].format(file_path, str(e)), logger.ERROR)
            return None

    def start(self):
        self.own, dummy = self.__owner, self.own
        del self.__owner
        dummy.replacement(self.own)

    def config_save(self, final=False, forced=False):
        if final:
            if self._save_me_later:
                self._save_me_later = False
                self._config_save()
        elif self.gts('lazy_record') and not forced:
            self._save_me_later = True
        else:
            self._save_me_later = False
            self._config_save()

    def _config_save(self):
        wtime = time.time()

        config = ConfigParserOnOff()
        for key, val in self.items():
            if isinstance(val, dict):
                config[key] = val

        with open(self.path['settings'], 'w', encoding='utf8') as configfile:
            config.write(configfile)
        self.log(LNG['save_for'].format(utils.pretty_time(time.time() - wtime)), logger.INFO)
        self.own.say_info(LNG['save'])

    def models_load(self):
        self.path['models_list'] = []
        if not os.path.isdir(self.path['models']):
            msg = LNG['miss_models'].format(self.path['models'])
            self.log(msg, logger.INFO)
            self.own.say_info(msg)
            return

        count = 0
        allow = self.get_allow_models()
        for file in self.get_all_models():
            full_path = os.path.join(self.path['models'], file)
            if os.path.isfile(full_path):
                if not allow or file in allow:
                    self.path['models_list'].append(full_path)
                    count += 1

        msg = LNG['models_count_call'].format(count)
        self.log(msg, logger.INFO)
        self.own.say_info(msg)

    def config_load(self):
        wtime = time.time()
        if not os.path.isfile(self.path['settings']):
            self.log(LNG['miss_settings'].format(self.path['settings']), logger.INFO)
            return True
        updater = ConfigUpdater(self, self.log)
        count = updater.from_ini(self.path['settings'])
        wtime = time.time() - wtime
        self.lang_init()
        self.log(LNG['load_for'].format(count, utils.pretty_time(wtime)), logger.INFO)
        self.own.say_info(LNG['load'])
        return updater.save_ini

    def lang_init(self):
        lang = self.gts('lang')
        deep_check = self.gts('lang_check')
        err = languages.set_lang(lang, None if not deep_check else self.log)
        if err:
            self.log(LNG['err_lng'].format(lang, err), logger.ERROR)
        self.log(LNG['lng_load_for'].format(lang, utils.pretty_time(languages.set_lang.load_time)), logger.INFO)

    def update_from_external(self, data: str or dict) -> dict or None:
        cu = ConfigUpdater(self, self.log)
        if isinstance(data, str):
            result = cu.from_json(data)
        elif isinstance(data, dict):
            result = cu.from_external_dict(data)
        else:
            self.log('Unknown settings type: {}'.format(type(data)), logger.ERROR)
            return None
        if result:
            return cu.diff
        else:
            return None

    def print_cfg_change(self):
        self.log(LNG['cfg_up'])

    def print_cfg_no_change(self):
        self.log(LNG['cfg_no_change'])

    def update_from_dict(self, data: dict) -> bool:
        return self._cfg_update(ConfigUpdater(self, self.log).from_dict(data))

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
            msg = LNG['miss_tts_cache'].format(cache_path)
            self.log(msg)
            self.own.say_info(msg)
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
            self.log(LNG['delete_wrong_files'].format(', '.join(wrong_files)), logger.WARN)

        normal_size = not files or current_size < max_size or max_size < 0
        say = LNG['tts_cache_size'].format(
            utils.pretty_size(current_size),
            LNG['tts_cache_act_list'][0] if normal_size else LNG['tts_cache_act_list'][1]
        )
        self.log(say, logger.INFO)

        if normal_size:
            return
        self.own.say_info(say)

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
        self.log(LNG['delete_files'].format(', '.join(deleted)))
        msg = LNG['deleted_files'].format(deleted_files, utils.pretty_size(current_size))
        self.log(msg, logger.INFO)
        self.own.say_info(msg)

    def _make_dir(self, path: str):
        if not os.path.isdir(path):
            self.log(LNG['create_dir'].format(path), logger.INFO)
            os.makedirs(path)

    def _lost_file(self, path: str):
        if not os.path.isfile(path):
            msg = LNG['miss_file_fixme'].format(path)
            self.log(msg, logger.CRIT)
            self.own.say(msg)

    def _first(self):
        if not self.gts('ip'):
            self['settings']['ip'] = utils.get_ip_address()
            return True
        return False

    def _say_ip(self):
        if not (self['smarthome']['outgoing_socket'] or self['smarthome']['ip']):
            msg = LNG['say_ip'].format(self.gts('ip'))
            self.log(msg, logger.WARN)
            self.own.say(msg)

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
