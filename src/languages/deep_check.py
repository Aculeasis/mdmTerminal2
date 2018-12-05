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
        self._warn = 0
        self._err = 0
        self._all = 0

    def log(self, msg, lvl=INFO):
        self.__log(msg, lvl=lvl)

    def start(self):
        self.log('')
        self.log('Start deep check module \'{}\' ...'.format(self._module))

    def end(self):
        self.log('')
        if self._warn:
            self.log('Found {} warnings'.format(self._warn), WARN)
        if self._err:
            self.log('Found {} errors'.format(self._err), ERROR)
        self.log('End deep check module \'{}\', check {} params.'.format(self._module, self._all))
        self.log('')

    def check(self, dict_name, old, new):
        self.log('Checking \'{}\' dictionary...'.format(dict_name))
        for key in old:
            self._all += 1
            if dict_name in self.NO_CHECK_DICT:
                continue
            if key not in new:
                self.log('Key \'{}\' missing'.format(key), ERROR)
                self._err += 1
                continue
            if not isinstance(old[key], type(new[key])):
                self._log('type', key, type(old[key]), type(new[key]), old[key], new[key], WARN)
                self._warn += 1
                continue
            if isinstance(old[key], (dict, list, set, tuple)):
                old_len = len(old[key])
                new_len = len(new[key])
                if old_len != new_len:
                    self._log('len', key, old_len, new_len, old[key], new[key], WARN)
                    self._warn += 1
                continue
            if isinstance(old[key], str):
                # Сравниваем количество замен {}.
                # TODO: использовать регексп, для {index}, {kwarg}
                old_count = old[key].count('{}')
                new_count = new[key].count('{}')
                if old_count != new_count:
                    self._log('count {}', key, old_count, new_count, old[key], new[key], WARN)
                    self._warn += 1

        # Ищем ключи которых нет в старых настройках
        for key in new:
            if key not in old:
                self.log('Found new key \'{}\'. May be this typo? Val: {}'.format(key, new[key]), ERROR)
                self._err += 1
                self._all += 1

    def _log(self, name, key, old_e, new_e, old, new, lvl):
        msg1 = 'Key \'{}\' {} different. Old: {}, new: {}...'.format(key, name, old_e, new_e)
        msg2 = 'Key \'{}\' values old: \'{}, new: \'{}\'. This is normal?'.format(key, old, new)
        self.log(msg1, lvl)
        self.log(msg2, lvl)
