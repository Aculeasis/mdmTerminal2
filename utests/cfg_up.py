import json
import unittest
from copy import deepcopy

import main
from lib.tools import config_updater


def dummy(*_, **__):
    pass


def new_updater():
    return config_updater.ConfigUpdater(CFG(), dummy)


def CFG():
    return deepcopy(main.CFG)


class ConfigUpdater(unittest.TestCase):
    ADD_5 = {'ip_server': '', 'ip': 1, 'two__': '2', 'three__': 3, 'four__': '4'}
    TXT_4 = '{"PROVIDERTTS":"NoYandex","APIKEYTTS":"y_key","PROVIDERSTT":"NoGoogle","APIKEYSTT":"g_key",' \
            '"ALARMKWACTIVATED":"1","ALARMTTS":"1","ALARMSTT":"1","newer__":{"fdfd":"777"}}'

    def test_self(self):
        updater = new_updater()
        self.assertEqual(updater.from_dict(CFG()), 0)
        self.assertEqual(updater._updated_count, 0)
        self.assertEqual(updater._updated_count, updater._change_count)
        self.assertFalse(updater.save_ini)

    def test_5(self):
        updater = new_updater()
        self.assertEqual(updater.from_dict({'be never': self.ADD_5}), 5)
        self.assertFalse(updater.save_ini)

    def test_5_0_str(self):
        add = json.dumps({'be never': self.ADD_5})
        updater = new_updater()
        self.assertEqual(updater.from_json(add), 0)
        self.assertFalse(updater.save_ini)

    def test_5_4_str(self):
        add = json.dumps(self.ADD_5)
        updater = new_updater()
        self.assertEqual(updater.from_json(add), 4)
        self.assertTrue(updater.save_ini)

    def test_5_5_dict(self):
        updater = new_updater()
        self.assertEqual(updater.from_dict({'settings': self.ADD_5}), 5)
        self.assertFalse(updater.save_ini)

    def test_prov(self):
        updater = new_updater()
        self.assertEqual(updater.from_json(self.TXT_4), 4)
        self.assertTrue(updater.save_ini)
        self.assertEqual(updater.from_dict(CFG()), 2)
        self.assertFalse(updater.save_ini)
        self.assertEqual(updater.from_dict(CFG()), 0)
        self.assertFalse(updater.save_ini)

    def test_prov_proxy(self):
        txt_5 = self.TXT_4[:-1] + ',"proxy":{"enable": "1"}}'
        updater = new_updater()
        self.assertEqual(updater.from_json(txt_5), 5)
        self.assertTrue(updater.save_ini)
        self.assertEqual(updater.from_dict(CFG()), 3)
        self.assertFalse(updater.save_ini)
        self.assertEqual(updater.from_dict(CFG()), 0)
        self.assertFalse(updater.save_ini)
