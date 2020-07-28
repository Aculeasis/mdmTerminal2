import os

import logger
from utils import dict_from_file


def state_helper(def_state: dict, path: dict, log) -> tuple:
    no_ini = not os.path.isfile(path['settings'])
    no_state = not os.path.isfile(path['state'])
    if no_state and no_ini:
        return def_state, True, True

    ini_version, merge, state_save = 0, 0, True
    if not no_state:
        try:
            state = dict_from_file(path['state'])
            ini_version = state['system']['ini_version']
            merge = state['system']['merge']
        except RuntimeError as e:
            log('Broken {}, reset'.format(path['state']), logger.WARN)
            state = def_state
        else:
            state['system'] = def_state['system']
            state_save = False
    else:
        state = def_state

    m = _Merge(merge, state, path, log)

    return m.state, m.state['system']['ini_version'] > ini_version, state_save or m.state_save


class _Merge:
    def __init__(self, start: int, state: dict, path: dict, log):
        self.state_save = False
        self.state = state
        self.path = path

        end = state['system']['merge']
        for merge in range(start + 1, end + 1):
            name = 'merge_{}'.format(merge)
            if hasattr(self, name):
                msg = 'Merge {} ... '.format(merge)
                try:
                    getattr(self, name)()
                except Exception as e:
                    log('{}{}'.format(msg, e), logger.ERROR)
                else:
                    log('{}{}'.format(msg, 'ok'))
            self.state_save = True

    def merge_1(self):
        for key in ('backup', 'update'):
            file_path = os.path.join(self.path['data'], key + '.json')
            if os.path.isfile(file_path):
                data = dict_from_file(file_path)
                os.remove(file_path)
                if data and isinstance(data, dict):
                    if key == 'update':
                        key = 'updater'
                    self.state[key] = data
