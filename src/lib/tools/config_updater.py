import configparser
import json
import threading

import logger
import utils
from lib.tools.settings_tester import SETTINGS_TESTER


def _hard_test_option(value, tester) -> str or None:
    msg = None
    if callable(tester):
        try:
            test = tester(value)
        except Exception as e:
            return '{}'.format(e)
        else:
            if isinstance(test, str):
                msg = test or 'incorrect'
            elif isinstance(test, bool) and not test:
                msg = 'incorrect'
    return msg


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
        'ip_server': ('smarthome', 'ip'),
        'token': ('snowboy', ''),
        'clear_models': ('snowboy', ''),
    }
    # Полный перенос секции для любого источника кроме dict. {from: to}
    SECTION_TO_SECTION = {'mpd': 'music', 'majordomo': 'smarthome'}
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

    def _ini_version_updated(self, data: dict) -> tuple:
        try:
            file_ver = int(data['system'].pop('ini_version'))
        except (ValueError, TypeError, KeyError):
            file_ver = 0
        try:
            cfg_ver = int(self._cfg['system'].get('ini_version'))
        except (ValueError, TypeError, KeyError):
            pass
        else:
            update = cfg_ver > file_ver
            return update, data

    def _ini_to_cfg(self, path: str):
        cfg = configparser.ConfigParser()
        try:
            cfg.read(path, encoding='utf8')
        except UnicodeDecodeError as e:
            self._log('Config file {} has broken: {}'.format(path, e), logger.CRIT)
        data = {sec.lower(): dict(cfg[sec]) for sec in cfg.sections()}
        save_me, data = self._ini_version_updated(data)
        self._save_me |= save_me
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
            if not isinstance(data.get(section, {}), dict):
                self._log('Conflict found, section and key name match: \'{}\''.format(section), logger.ERROR)
                continue

            section = self.SECTION_TO_SECTION.get(section, section)
            if not new_key or not section or section not in sections:
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
        data = self._section_to_section(data)
        self._settings_adapter(data)
        for key, val in data.items():
            if not isinstance(val, dict):
                self._print_result('Section must be dict. {}: {}'.format(key, val), logger.CRIT)
                continue
            external = self._source in self.EXTERNALS
            tester = SETTINGS_TESTER.get(key)
            self._recursive_parser(self._cfg, self._new_cfg, key, val, external, tester)

    def _recursive_parser(self, cfg: dict, cfg_diff: dict, key, val, external, tester):
        if not isinstance(key, str):
            self._log('Key type must be string only, not {}. Ignore key \'{}\''.format(type(key), key), logger.ERROR)
            return
        key = key if not external else key.lower()
        if isinstance(val, dict) and isinstance(cfg.get(key, {}), dict):  # секция
            self._parse_section_element(cfg, cfg_diff, key, val, external, tester)
        elif external and isinstance(val, (dict, list, set, tuple)):
            msg = 'Invalid type of option \'{}:{}\' {}, from server. Ignoring.'.format(key, val, type(val))
            self._log(msg, logger.ERROR)
        else:
            if self._parse_param_element(cfg, cfg_diff, key, val, self._source == 2, tester):
                self._change_count += 1

    def _parse_section_element(self, cfg: dict, cfg_diff: dict, key, val, external, tester):
        if external and key not in cfg:  # Не принимаем новые секции от сервера
            self._log('Ignore new section from server \'{}:{}\''.format(key, val), logger.ERROR)
            return
        cfg_diff[key] = cfg_diff.get(key, {})
        for key_, val_ in val.items():
            tester_key = tester.get(key_) if isinstance(tester, dict) else None
            self._recursive_parser(cfg.get(key, {}), cfg_diff[key], key_, val_, external, tester_key)
        if not cfg_diff[key] and key in cfg:  # Удаляем существующие пустые секции
            del cfg_diff[key]

    def _parse_param_element(self, cfg: dict, cfg_diff: dict, key, val, from_json, tester):
        if from_json and isinstance(val, str) and key not in self.NOT_LOWER:
            val = val.lower()
        source_type = type(cfg.get(key, ''))
        try:
            if val is None and self._source == 2:
                # ignore None (null) from server
                raise ValueError('Ignore \'NoneType\'')
            tmp = source_type(val) if source_type != bool else utils.bool_cast(val)
        except (ValueError, TypeError) as e:
            old = repr(cfg.get(key, 'old value'))
            msg = 'Wrong type of option \'{}:{}\' {}, keep {}. {}'.format(key, val, type(val), old, e)
            self._log(msg, logger.ERROR)
        else:
            if key not in cfg or tmp != cfg[key]:
                test = _hard_test_option(tmp, tester)
                if test:
                    old = repr(cfg.get(key, 'old value'))
                    msg = 'Wrong value of option \'{}:{}\', keep {}. {}'.format(key, tmp, old, test)
                    self._log(msg, logger.ERROR)
                    return False
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

            self._save_me |= self._parse_param_element(cfg.get(sec, {}), cfg[sec], key_move, val, False, None)

            if not cfg[sec] and add_empty:
                del cfg[sec]
            elif add_empty and sec not in self._cfg:
                self._cfg[sec] = {}
            # Удаляем перемещенный ключ из settings
            data.pop(key)

    def _section_to_section(self, data: dict) -> dict:
        if not (self._source and data and self.SECTION_TO_SECTION):
            return data
        for from_, to_ in self.SECTION_TO_SECTION.items():
            if from_ in data:
                if to_ not in data:
                    data[to_] = {}
                data[to_].update(data.pop(from_))
        return data

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
