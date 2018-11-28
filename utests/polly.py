import time
import unittest

from lib.polly_signing import signing

ACCESS_KEY_ID = 'access_key_id'
SECRET_KEY_ID = 'secret_access_key'
REGION = 'eu-west-3'
PARAMS_DICT = {'one': 1, 'two': 2}

TIME = 1543375527.3228908

ENDPOINT = 'https://polly.eu-west-3.amazonaws.com/v1/speech'
PARAMS = b'{"one": 1, "two": 2}'
HEADERS = {
    'Content-Type': 'application/json',
    'X-Amz-Date': '20181128T032527Z',
    'Authorization': 'AWS4-HMAC-SHA256 Credential=access_key_id/20181128/eu-west-3/polly/aws4_request, '
                     'SignedHeaders=content-type;host;x-amz-date, '
                     'Signature=40594d974e48bc3b3a05dd2e29581872eda6c8cb787cdfb3e4d6a4b427dc2377'
}


def fake_time():
    return TIME


class Polly(unittest.TestCase):
    def test_signing(self):
        bk = time.time
        time.time = fake_time
        endpoint, params, headers = signing(PARAMS_DICT, ACCESS_KEY_ID, SECRET_KEY_ID, REGION)
        time.time = bk
        self.assertEqual(endpoint, ENDPOINT)
        self.assertEqual(params, PARAMS)
        self.assertEqual(headers, HEADERS)
