import unittest

from lib.STT import xml_yandex, UnknownValueError

xml_ok = """
<recognitionResults success="1">
\t<variant confidence="0.69">твой номер 212-85-06</variant>
\t<variant confidence="0.7">твой номер 213-85-06</variant>
</recognitionResults>
"""

xml_no1 = """
<recognitionResults success="0">
\t<variant confidence="0.69">твой номер 212-85-06</variant>
\t<variant confidence="0.7">твой номер 213-85-06</variant>
</recognitionResults>
"""

xml_no2 = '<recognitionResults success="0">'

xml_no3 = """
<recognitionResults success="0">
</recognitionResults>
"""

xml_broken = """
<recognitionResults success="ok">
</recognitionResults>
"""

xml_err1 = """
\t<variant confidence="0.7">твой номер 213-85-06</variant>
"""

xml_err2 = """
<recognitionResults success="1">
твой номер 212-85-06</variant>
\t<variant confidence="0.7">твой номер 213-85-06</variant>
</recognitionResults>
"""


class YandexXML(unittest.TestCase):
    def _raises(self, who, what):
        self.assertTrue(False, '{} must be raised for: {}'.format(who, what))

    def _xml_no(self, data):
        err = ''
        try:
            xml_yandex(data)
        except UnknownValueError as e:
            err = str(e)
        except RuntimeError as e:
            self.assertTrue(False, '{}: {}'.format(str(e), data))
        else:
            self._raises('UnknownValueError', data)
        self.assertEqual(err, 'No variants')

    def _xml_err(self, data, msg):
        err = ''
        try:
            xml_yandex(data)
        except UnknownValueError as e:
            self.assertTrue(False, '{}: {}'.format(str(e), data))
        except RuntimeError as e:
            err = str(e)
        else:
            self._raises('RuntimeError', data)
        self.assertEqual(err, msg)

    def test_ok(self):
        self.assertEqual(xml_yandex(xml_ok), 'твой номер 212-85-06')

    def test_no_variants(self):
        for data in (xml_no1, xml_no2, xml_no3):
            self._xml_no(data)

    def test_broken(self):
        try:
            xml_yandex(xml_broken)
        except RuntimeError as e:
            e = str(e)
            self.assertEqual(e, 'xml: root attribute broken - \'{}\''.format('o'))
        else:
            self._raises('RuntimeError', xml_broken)

    def test_err(self):
        variants = (
            (xml_err1, 'xml: root attribute not found, not XML?'),
            (xml_err2, 'xml: broken XML'),
        )
        for data, msg in variants:
            self._xml_err(data, msg)
