import unittest

from lib.ip_storage import make_interface_storage

ips_str = '192.168.1.0/24,127.0.0.1 , 192.0.2.0/24, 8.8.8.8'
ips_wrong = '111,11fdfd111,'


class IPStorage(unittest.TestCase):
    def _raises(self, who, what):
        self.assertTrue(False, '{} must be raised for: {}'.format(who, what))

    def test_ips_wrong(self):
        try:
            _ = make_interface_storage(ips_wrong)
        except RuntimeError:
            pass
        except Exception as e:
            self._raises('RuntimeError', '{} not {}'.format(ips_wrong, e))
        else:
            self._raises('RuntimeError', ips_wrong)

    def test_ip_yes(self):
        ips = make_interface_storage(ips_str)
        self.assertTrue('192.168.1.1' in ips)
        self.assertTrue('192.168.1.2' in ips)
        self.assertTrue('192.168.1.200' in ips)

        self.assertTrue('192.0.2.1' in ips)
        self.assertTrue('192.0.2.18' in ips)

        self.assertTrue('8.8.8.8' in ips)
        self.assertTrue('127.0.0.1' in ips)

    def test_ip_yes_always(self):
        ips = make_interface_storage(',,, , , ')
        self.assertTrue('192.168.1.1' in ips)
        self.assertTrue('' in ips)
        self.assertTrue('----!----' in ips)

    def test_ip_no(self):
        ips = make_interface_storage(ips_str)
        self.assertFalse('192.168.2.1' in ips)
        self.assertFalse('192.168.2.2' in ips)
        self.assertFalse('192.168.2.200' in ips)

        self.assertFalse('192.8.2.1' in ips)
        self.assertFalse('192.8.2.18' in ips)

        self.assertFalse('7.7.7.7' in ips)
        self.assertFalse('127.0.0.9' in ips)

        self.assertFalse('-------------' in ips)
