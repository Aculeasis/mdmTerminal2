import logging

INFO = logging.INFO
WARN = logging.WARN
ERROR = logging.ERROR


class DeepChecker:
    # Не сравниваем эти словари, они могут быть разными
    NO_CHECK_DICT = ('RHVOICE_SPEAKER', 'AWS_SPEAKER')

    def __init__(self, print_, module):
        self.__log = print_
        self._module = module
        self._warn, self._err, self._info, self._all = [0] * 4

    def log(self, msg, lvl=INFO):
        self.__log(msg, lvl=lvl)

    def start(self):
        self.log('')
        self.log('Start deep check module \'{}\' ...'.format(self._module))

    def end(self):
        self.log('')
        if self._info:
            self.log('Found {} info'.format(self._info))
        if self._warn:
            self.log('Found {} warnings'.format(self._warn), WARN)
        if self._err:
            self.log('Found {} errors'.format(self._err), ERROR)
        self.log('End deep check module \'{}\', check {} params.'.format(self._module, self._all))
        self.log('')

    def check(self, dict_name, old: dict, new: dict):
        self.log('Checking \'{}\' dictionary...'.format(dict_name))
        for key, old_val in old.items():
            self._all += 1
            if dict_name in self.NO_CHECK_DICT:
                continue
            old_val = key if old_val is None and isinstance(key, str) else old_val
            new_val = new.get(key, None)
            new_val = key if new_val is None and isinstance(key, str) else new_val
            if key not in new:
                self.log('Key \'{}\' missing'.format(key), ERROR)
                self._err += 1
                continue
            if not isinstance(old_val, type(new_val)):
                self._log('type', key, type(old_val), type(new_val), old_val, new_val, WARN)
                self._warn += 1
                continue
            if isinstance(old_val, (dict, list, set, tuple)):
                old_len = len(old_val)
                new_len = len(new_val)
                if old_len != new_len:
                    self._log('len', key, old_len, new_len, old_val, new_val, WARN)
                    self._warn += 1
                continue
            if isinstance(old_val, str):
                # Сравниваем количество замен {}.
                # TODO: использовать регексп, для {index}, {kwarg}
                old_count = old_val.count('{}')
                new_count = new_val.count('{}')
                if old_count != new_count:
                    self._log('count {}', key, old_count, new_count, old_val, new_val, WARN)
                    self._warn += 1

        # Ищем ключи которых нет в старых настройках
        all_diff = 0
        for key in new:
            if key not in old:
                if dict_name not in self.NO_CHECK_DICT:
                    self.log('Found new key \'{}\'. This typo? Val: {}'.format(key, new[key]), ERROR)
                    self._err += 1
                else:
                    all_diff += 1
                self._all += 1
        if all_diff:
            self.log('Founds {} new keys. OK!?'.format(all_diff))
            self._info += all_diff

    def _log(self, name, key, old_e, new_e, old, new, lvl):
        msg1 = 'Key \'{}\' {} different. Old: {}, new: {}...'.format(key, name, old_e, new_e)
        msg2 = 'Key \'{}\' values old: \'{}, new: \'{}\'. This is normal?'.format(key, old, new)
        self.log(msg1, lvl)
        self.log(msg2, lvl)
