#!/usr/bin/env python3

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.abspath(sys.path[0]), 'src'))

import run
from loader import Loader
from utils import SignalHandlerDummy
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
    home = run.HOME
    path = run.get_path(home)
    cfg = run.get_cfg()
    state = run.get_state()
    # Меняем настройки
    path['settings'] = '{}.test'.format(path['settings'])
    path['state'] = '{}.test.json'.format(path['state'])
    cfg['log'].update({'file_lvl': 'warn', 'print_lvl': 'warn', 'file': os.path.join(home, 'mdmt2.log.test')})
    try:
        loader = Loader(init_cfg=cfg, init_state=state, path=path, sig=SignalHandlerDummy())
        loader.start_all_systems()
        time.sleep(10)
        loader.stop_all_systems()
        err = check_log(cfg['log']['file'])
    finally:
        for target in [path['settings'], path['state'], cfg['log']['file']]:
            if os.path.isfile(target):
                os.remove(target)
    return err


if __name__ == '__main__':
    mono_err = tests_mono()
    unittest.main(verbosity=2, exit=False)
    if mono_err:
        print()
        raise RuntimeError('{}'.format(', '.join(mono_err)))
