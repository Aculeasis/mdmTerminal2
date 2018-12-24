import unittest

from lib.snowboy_training import pretty_errors


class SNPrettyErrors(unittest.TestCase):
    def test_1(self):
        data = '{"voice_samples":[{},{"wave":["Hotword is too long"]},{}]}'
        result = "'Hotword is too long' for samples: 2"
        self.assertEqual(pretty_errors(data), result)

    def test_2(self):
        data = '{"voi54ce_sa45mples":[{},{"wa54ve":["Hot54word is too long"]},{}]}'
        self.assertEqual(pretty_errors(data), data)

    def test_3(self):
        data = '{"detail":"Authentication credentials were not provided."}'
        result = 'Authentication credentials were not provided.'
        self.assertEqual(pretty_errors(data), result)

    def test_4(self):
        data = '{"voice_samples":[{"wave":["short"]},{"wave":["long", "short"]},{}]}'
        result = "'short' for samples: 1, 2;'long' for samples: 2"
        self.assertEqual(pretty_errors(data), result)
