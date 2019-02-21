import re

import requests

from utils import REQUEST_ERRORS


def _load():
    url = 'https://raw.githubusercontent.com/Aculeasis/mdmTerminal2/master/src/default_settings.py'
    try:
        rq = requests.get(url, timeout=10)
    except REQUEST_ERRORS:
        return None
    if not rq.ok:
        return None
    return rq.text


def get_latest_version() -> tuple:
    data = _load()
    if not data:
        return 0, 0, 0
    try:
        # 'VERSION': (0, 8, 2),
        found = re.search('VERSION\': \((.+?)\)', data).group(1).split(', ')
        found = tuple(int(val) for val in found)
        if len(found) != 3:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        return 0, 0, 0
    return found


def available_version_msg(current: tuple) -> str:
    def to_str(v_: tuple):
        return '.'.join(str(x) for x in v_)

    msg_last = 'You are using {}mdmTerminal2 version {}'
    msg_new = 'You are using mdmTerminal2 version {}, however version {} is available.'
    check_failed = 'version check failed :('
    is_latest = 'latest '

    new_v = get_latest_version()
    if new_v == (0, 0, 0):
        msg = '{}, {}'.format(msg_last.format('', to_str(current)), check_failed)
    elif new_v > current:
        msg = msg_new.format(to_str(current), to_str(new_v))
    else:
        msg = '{}.'.format(msg_last.format(is_latest, to_str(current)))
    return msg
