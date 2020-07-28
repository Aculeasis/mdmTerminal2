import json
from functools import lru_cache

import requests
import urllib3

import logger
from utils import singleton

WIKI_TARGET = 'https://github.com/Aculeasis/mdmTerminal2/wiki/settings.ini'


@singleton
class WikiParser:
    WIKI_JSON = 'wiki_dump'

    def __init__(self, cfg, log):
        self.cfg = cfg
        self.log = log

    def get(self) -> dict:
        return self._get(self.cfg.ini_version)

    @lru_cache(maxsize=1)
    def _get(self, ini: int) -> dict:
        try:
            return self._get_descriptions(ini)
        except RuntimeError as e:
            self.log('Wiki parsing error: {}'.format(e), logger.ERROR)
            return {}

    def _get_descriptions(self, ini: int) -> dict:
        dsc = self.cfg.load_dict(self.WIKI_JSON)
        if not dsc or not isinstance(dsc, list) or len(dsc) != 2 or not isinstance(dsc[0], int) \
                or not isinstance(dsc[1], dict):
            self.log('Initial generate {}.json from wiki...'.format(self.WIKI_JSON), logger.INFO)
            dsc = self._init_descriptions(ini)
        if dsc[0] < ini:
            self.log('{}.json is outdated ({} < {}), update...'.format(self.WIKI_JSON, dsc[0], ini), logger.INFO)
            dsc = self._init_descriptions(ini)
        return dsc[1]

    def _init_descriptions(self, ini: int) -> list:
        dsc = [ini, get_descriptions_from_wiki()]
        self.cfg.save_dict(self.WIKI_JSON, dsc, True)
        self.log('SUCCESS!', logger.INFO)
        return dsc


def get_wiki_direct(url: str) -> str:
    __WIKI_RAW = 'https://raw.githubusercontent.com/wiki/{user}/{repo}/{page}.md'
    url = url.split('/')
    page = url[-1]
    repo = url[-3]
    user = url[-4]
    return __WIKI_RAW.format(user=user, repo=repo, page=page)


def get_body(url: str) -> str:
    try:
        res = requests.get(url)
    except (requests.exceptions.RequestException, urllib3.exceptions.NewConnectionError) as e:
        raise RuntimeError(e)
    if not res.ok:
        raise RuntimeError('Response error from {}, {}: {}'.format(url, res.status_code, res.reason))
    body = res.text
    if not body:
        raise RuntimeError('Empty response from {}'.format(url))
    return body


def get_settings_list(txt: str) -> list:
    sep = '```'
    start, end = None, None
    txt = txt.split('\n')
    for idx in range(len(txt)):
        if txt[idx].startswith(sep):
            if not start:
                start = idx
            else:
                end = idx
                break
    if not (start and end) or end < start:
        raise RuntimeError('Wrong start-end: {}-{}'.format(start, end))
    return txt[start:end]


def settings_list_to_sections(cfg: list) -> dict:
    result = {}
    section = None
    for line in cfg:
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
            result[section] = []
        elif section:
            result[section].append(line)
    return result


def settings_options_parse(cfg: dict) -> dict:
    return {key: _settings_option_parse(val) for key, val in cfg.items()}


def _settings_option_parse(cfg: list) -> dict:
    if cfg[-1]:
        cfg.append('')
    result = {}
    option = None
    buff = []
    for line in cfg:
        if line.startswith('#'):
            line = line[1:]
            if line.startswith(' '):
                line = line[1:]
            buff.append(line)
        elif not line:
            if not buff:
                continue
            if option not in result:
                result[option] = []
            result[option].extend(buff)
            buff = []
        elif ' ' in line and '=' in line:
            if option and option not in result and buff:
                result[option] = []
                result[option].extend(buff)
            option = line.split('=', 1)[0].strip()
    result = _settings_option_parse_suppressing_1(result)
    result = _settings_option_parse_suppressing_2(result)
    result = _settings_option_parse_suppressing_3(result)
    return result


def _settings_option_parse_suppressing_1(result: dict) -> dict:
    test = None
    test_count = 0
    count = 0
    for val in result.values():
        count += 1
        if test is None:
            test = val
            test_count += 1
        elif test == val:
            test_count += 1
        else:
            test = val
    if test_count > 1 and test_count == count and test:
        result = {None: test}
    return result


def _settings_option_parse_suppressing_2(result: dict) -> dict:
    for key, val in result.items():
        if isinstance(val, list):
            result[key] = '\n'.join(val)
    return result


def _settings_option_parse_suppressing_3(result: dict) -> dict:
    if 'null' in result:
        print('FIXME! \'null\'-key has found!: {}'.format(repr(result['null'])))
    if None in result:
        result['null'] = result.pop(None)
    return result


def get_descriptions_from_wiki() -> dict:
    return settings_options_parse(settings_list_to_sections(get_settings_list(get_body(get_wiki_direct(WIKI_TARGET)))))


def __main():
    cfg = get_descriptions_from_wiki()
    print()
    print(cfg)
    print()
    print(json.dumps(cfg, ensure_ascii=False, indent=4))
    print()


if __name__ == '__main__':
    __main()
