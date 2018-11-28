#!/usr/bin/env python3

import os
import sys
import time
import unittest
from copy import deepcopy

sys.path.insert(0, os.path.join(os.path.abspath(sys.path[0]), 'src'))

import main
from loader import Loader
# noinspection PyUnresolvedReferences
from utests import *


def test_line(include: list, line: str):
    for test in include:
        if line.find(test) > 0:
            return True
    return False


def check_log(log_file):
    include = ['WARNING', 'ERROR', 'CRITICAL']
    exclude = ['Error get list microphones', 'Терминал еще не настроен']
    result = []
    if not os.path.isfile(log_file):
        return result
    with open(log_file) as fp:
        for line in fp.readlines():
            if test_line(include, line) and not test_line(exclude, line):
                result.append(line.strip('\n').strip())
    return result


def tests_mono():
    def dummy(*_, **__):
        pass

    home = main.HOME
    path = main.get_path(home)
    cfg = deepcopy(main.CFG)
    # Меняем настройки
    test_settings = '{}.test'.format(path['settings'])
    path['settings'] = test_settings
    test_log_file = os.path.join(home, 'mdmt2.log.test')
    cfg['log'].update({'file_lvl': 'warn', 'print_lvl': 'warn', 'file': test_log_file})
    try:
        loader = Loader(init_cfg=cfg, path=path, die_in=dummy)
        loader.start()
        time.sleep(10)
        loader.stop()
        err = check_log(test_log_file)
    finally:
        for target in [test_settings, test_log_file]:
            if os.path.isfile(target):
                os.remove(target)
    return err


if __name__ == '__main__':
    mono_err = tests_mono()
    print()
    unittest.main(verbosity=2)
    if mono_err:
        print()
        raise RuntimeError('{}'.format(', '.join(mono_err)))
