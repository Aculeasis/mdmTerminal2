#!/usr/bin/env python3

import os
import time

import main
from loader import Loader


def check_log(log_file):
    include = ['WARNING', 'ERROR', 'CRITICAL']
    exclude = []
    result = []
    if not os.path.isfile(log_file):
        return result
    with open(log_file) as fp:
        for line in fp.readlines():
            if [True for k in include if line.find(k) > 0] and not [True for k in exclude if line.find(k) > 0]:
                result.append(line.strip('\n').strip())
    return result


def tests_mono():
    def dummy(*_, **__):
        pass

    home = main.HOME
    path = main.get_path(home)
    cfg = main.CFG.copy()
    # Меняем настройки
    test_settings = '{}.test'.format(path['settings'])
    path['settings'] = test_settings
    test_log_file = os.path.join(home, 'mdmt2.log.test')
    cfg['log'].update({'file_lvl': 'warn', 'print_lvl': 'warn', 'file': test_log_file})
    try:
        loader = Loader(init_cfg=cfg, path=path, die_in=dummy)
        loader.start()
        time.sleep(25)
        loader.stop()
        print()
        for err in check_log(test_log_file):
            print(err)
    finally:
        for target in [test_settings, test_log_file]:
            if os.path.isfile(target):
                os.remove(target)


if __name__ == '__main__':
    tests_mono()
