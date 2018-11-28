
import datetime
import hashlib
import hmac
import json
import time
__ALL__ = ['signing']

SERVICE = 'polly'
API = '/v1/speech'
POLLY_HOST = 'polly.{}.amazonaws.com'
METHOD = 'POST'
ALGORITHM = 'AWS4-HMAC-SHA256'
CONTENT_TYPE = 'application/json'
SIGNED_HEADERS = 'content-type;host;x-amz-date'
AWS_REGIONS = {
    'us-east-2', 'us-east-1', 'us-west-1', 'us-west-2',
    'ap-south-1', 'ap-northeast-2', 'ap-southeast-1', 'ap-southeast-2', 'ap-northeast-1',
    'ca-central-1',
    'eu-central-1', 'eu-west-1', 'eu-west-2', 'eu-west-3',
    'sa-east-1',
}


def signing(params, access_key_id, secret_access_key, region):
    # requests.post(endpoint, data=request_parameters, headers=headers)
    _must_be_str('access_key_id', access_key_id)
    _must_be_str('secret_access_key', secret_access_key)
    host, endpoint = get_host_and_endpoint(region)
    try:
        params = json.dumps(params, ensure_ascii=False).encode()
    except TypeError as e:
        raise RuntimeError('Wrong params: {}'.format(e))
    amz_date, date_stamp = get_dates()
    canonical_request = get_canonical_request(params, host, amz_date)
    credential_scope = get_credential_scope(date_stamp, region)
    string_to_sign = get_string_to_sign(amz_date, credential_scope, canonical_request)
    signature = get_signature(secret_access_key, date_stamp, region, string_to_sign)
    authorization_header = get_authorization_header(access_key_id, credential_scope, signature)
    headers = get_headers(amz_date, authorization_header)
    return endpoint, params, headers


def _must_be_str(name, param):
    if not param or not isinstance(param, str):
        raise RuntimeError('{} must not be a empty string'.format(name))


def get_host_and_endpoint(region):
    if region not in AWS_REGIONS:
        raise RuntimeError('Incorrect AWS region: {}'.format(region))
    host = POLLY_HOST.format(region)
    return host, 'https://{}{}'.format(host, API)


# Key derivation functions. See:
# http://docs.aws.amazon.com/general/latest/gr/signature-v4-examples.html#signature-v4-examples-python
# https://stackoverflow.com/questions/41793119/use-aws-apis-with-python-to-use-polly-services
def _sign(key, msg):
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()


def _get_signature_key(key, date_stamp, region):
    k_date = _sign(('AWS4' + key).encode(), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, SERVICE)
    k_signing = _sign(k_service, 'aws4_request')
    return k_signing


def get_dates():
    t = datetime.datetime.utcfromtimestamp(time.time())
    return t.strftime('%Y%m%dT%H%M%SZ'), t.strftime('%Y%m%d')


def _get_canonical_headers(host, amz_date):
    return 'content-type:{}\nhost:{}\nx-amz-date:{}\n'.format(CONTENT_TYPE, host, amz_date)


def get_canonical_request(params, host, amz_date):
    payload_hash = hashlib.sha256(params).hexdigest()
    canonical_headers = _get_canonical_headers(host, amz_date)
    return '\n'.join((METHOD, API, '', canonical_headers, SIGNED_HEADERS, payload_hash))


def get_credential_scope(date_stamp, region):
    return '/'.join((date_stamp, region, SERVICE, 'aws4_request'))


def get_string_to_sign(amz_date, credential_scope, canonical_request):
    return '\n'.join((ALGORITHM, amz_date, credential_scope, hashlib.sha256(canonical_request.encode()).hexdigest()))


def get_signature(secret_access_key, date_stamp, region, string_to_sign):
    signing_key = _get_signature_key(secret_access_key, date_stamp, region)
    return hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()


def get_authorization_header(access_key_id, credential_scope, signature):
    return '{} Credential={}/{}, SignedHeaders={}, Signature={}'.format(
        ALGORITHM, access_key_id, credential_scope, SIGNED_HEADERS, signature
    )


def get_headers(amz_date, authorization_header):
    return {
        'Content-Type': CONTENT_TYPE,
        'X-Amz-Date': amz_date,
        'Authorization': authorization_header
    }

