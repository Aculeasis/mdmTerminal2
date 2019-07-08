import unittest

from utils import url_builder


def test(ip_url):
    return url_builder(ip_url, def_path='/path', def_port=90)


url = 'http://test.test:90/path'
eq = (url, 'http://test.test:90', 'http://test.test', 'test.test', 'test.test:90/path', 'test.test:90')
ne = (
    'http://test.test:99/path', 'http://test.test:90/path2', 'http://test.test2:90/path', 'https://test.test:90/path'
    'http://test.test:99', 'https://test.test', 'test.test2', 'test.test:90/path2', 'test.test:96'
)


class URLBuilder(unittest.TestCase):
    def test_eq(self):
        for line in eq:
            self.assertEqual(url, test(line), '{}!={}'.format(repr(url), repr(line)))

    def test_ne(self):
        for line in ne:
            self.assertNotEqual(url, test(line), '{}=={}'.format(repr(url), repr(line)))
