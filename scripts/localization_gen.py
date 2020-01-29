import ast
import importlib.util
import os
import sys
import time
from collections import OrderedDict
import argparse
import googletrans

SRC_DIR = os.path.join(os.path.split(os.path.abspath(sys.path[0]))[0], 'src')
SRC_PRETTY = os.path.join('~')
LNG_DIR = os.path.join(SRC_DIR, 'languages')
DST_FILE = os.path.join(LNG_DIR, 'ru.py')
EXT = '.py'
WALK_SUBDIR = ('lib',)
TOP_IGNORE = ('test.py',)

HEADER_1 = """
def _config_pretty_models(_, count):
    ot = 'о'
    if count == 1:
        et = 'ь'
        ot = 'а'
    elif count in [2, 3, 4]:
        et = 'и'
    else:
        et = 'ей'
    pretty = ['ноль', 'одна', 'две', 'три', 'четыре', 'пять', 'шесть']
    count = pretty[count] if count < 7 else count
    return 'Загружен{} {} модел{}'.format(ot, count, et)"""

# === dicts header ===
LANG_CODE = {
    'IETF': 'ru-RU',
    'ISO': 'ru',
    'aws': 'ru-RU',
}

YANDEX_EMOTION = {
    'good'    : 'добрая',
    'neutral' : 'нейтральная',
    'evil'    : 'злая',
}

YANDEX_SPEAKER = {
    'jane'  : 'Джейн',
    'oksana': 'Оксана',
    'alyss' : 'Алиса',
    'omazh' : 'Омар',  # я это не выговорю
    'zahar' : 'Захар',
    'ermil' : 'Саня'  # и это
}

RHVOICE_SPEAKER = {
    'anna'     : 'Аня',
    'aleksandr': 'Александр',
    'elena'    : 'Елена',
    'irina'    : 'Ирина'
}

AWS_SPEAKER = {
    'Tatyana': 'Татьяна',
    'Maxim': 'Максим',
}
HEADER_DICTS = {
    'LANG_CODE': LANG_CODE,
    'YANDEX_EMOTION': YANDEX_EMOTION,
    'YANDEX_SPEAKER': YANDEX_SPEAKER,
    'RHVOICE_SPEAKER': RHVOICE_SPEAKER,
    'AWS_SPEAKER': AWS_SPEAKER,
}
# ======


LF = '\n'


class RawRepr(str):
    def __new__(cls, text):
        # noinspection PyArgumentList
        obj = str.__new__(cls, text)
        return obj

    def __repr__(self):
        return self


ASSIGNS = {
    'Загружено {} моделей': RawRepr('_config_pretty_models'),
}


class LIFOFixDict(OrderedDict):
    def __init__(self, *args, maxlen=30, **kwargs):
        self._max = maxlen
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        if key in self:
            del self[key]
        super().__setitem__(key, value)
        if 0 < self._max < len(self):
            self.popitem(False)


class Parser:
    def __init__(self, target='F'):
        self.result = OrderedDict()
        self.target = target
        self.line, self.class_, self.def_, self.filename = [None] * 4
        self.calls = 0
        self.phrases = set()
        self._store = LIFOFixDict()

    def parse(self, file_path, filename):
        self.line, self.class_, self.def_ = [None] * 3
        self.calls = 0
        self.phrases = set()
        self._store = LIFOFixDict()
        self.filename = filename
        w_time = time.time()
        try:
            with open(file_path, encoding='utf8') as fd:
                data = fd.read()
        except IOError as e:
            print('Error reading {}: {}'.format(file_path, e))
            return
        try:
            body = ast.parse(data).body
        except Exception as e:
            print('AST {}:{}'.format(file_path, e))
            return
        list(map(self._finder, body))
        w_time = time.time() - w_time
        if self.calls:
            print('Parse {} in {} sec. Founds {} calls, {} phrases'.format(
                filename, w_time, self.calls, len(self.phrases)))

    def _pw(self, msg):
        print('{}#L{}: {}; class={}, def={}'.format(self.filename, self.line, msg, self.class_, self.def_))

    def _store_set(self, val: ast.Assign):
        def _store(key_, val_):
            if isinstance(key_, ast.Name) and isinstance(key_.ctx, ast.Store) and val_ is not None:
                self._store[key_.id] = val_

        for key in val.targets:
            if isinstance(key, (ast.Tuple, ast.List)) and isinstance(val.value, (ast.Tuple, ast.List)) and \
                    isinstance(key.ctx, ast.Store):
                list(map(_store, key.elts, val.value.elts))
                return
            _store(key, val.value)

    def _store_get(self, name: str) -> str or None:
        val = self._store.pop(name, None)
        if val is None:
            return
        if not isinstance(val, ast.Str):
            self._pw('Wrong type by name. Name={}, type={}'.format(name, type(val)))
            return
        return val.s

    def _save(self, value: str, level):
        if value not in self.result:
            self.result[value] = []
        self.calls += 1
        self.phrases.add(value)
        self.result[value].append(
            {'class': self.class_, 'def': self.def_, 'line': self.line, 'file': self.filename, 'lvl': level}
        )

    def _call_probe(self, node: ast.Call, level):
        value = None
        if not node.args:
            self._pw('Call without args?')
        elif not isinstance(node.args[0], (ast.Name, ast.Str)):
            self._pw('First arg must be Name or Str, not {}'.format(type(node.args[0])))
        elif isinstance(node.args[0], ast.Name):
            if not isinstance(node.args[0].ctx, ast.Load):
                self._pw('Arg type={} not Load, WTF'.format(type(node.args[0].ctx)))
            else:
                value = self._store_get(node.args[0].id)
        else:
            value = node.args[0].s or None
            if not value:
                self._pw('Empty text?')
        if value:
            self._save(value, level)

    def _finder(self, node, level=0):
        self.line = getattr(node, 'lineno', self.line)
        if not level:
            self.class_, self.def_ = None, None
        if isinstance(node, ast.ClassDef) and not level:
            self.class_ = node.name
            self.def_ = None
        elif isinstance(node, ast.FunctionDef):
            if not level:
                self.def_ = node.name
                self.class_ = None
            elif level == 2 or not self.def_:
                self.def_ = node.name

        if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == self.target:
            self._call_probe(node, level)
        elif isinstance(node, ast.Assign):
            self._store_set(node)

        if isinstance(node, ast.AST):
            for _, b in ast.iter_fields(node):
                self._finder(b, level+1)
            # noinspection PyProtectedMember
            if node._attributes:
                # noinspection PyProtectedMember
                for a in node._attributes:
                    self._finder(getattr(node, a), level+1)
        elif isinstance(node, list):
            for x in node:
                self._finder(x, level+1)


def _read_lng_comments(file: str) -> list:
    with open(file, encoding='utf8') as fd:
        line = 'True'
        while not line.startswith('_LNG'):
            line = fd.readline()
            if not line:
                return []
            line = line.strip()

        result = []
        comment = ''
        while True:
            line = fd.readline()
            if not line:
                break
            line = line.strip()
            if line == '}':
                break
            if line.startswith('#'):
                comment = line[1:].lstrip()
            elif comment:
                result.append(comment)
        return result


def read_lng_comments(data: dict, file=DST_FILE) -> {}:
    try:
        comments = _read_lng_comments(file)
    except IOError as e:
        print('Error reading {}: {}'.format(file, e))
        comments = None
    if not comments:
        return {}
    keys = [x for x in data.keys()]
    if len(comments) != len(keys):
        print('Comments count={}, data keys={}. Mismatch.'.format(len(comments), len(keys)))
        return {}
    return dict(zip(keys, comments))


class Writter:
    def __init__(self, file):
        self._file = file
        self._fd = None

    def _wl(self, line: str or list):
        if not isinstance(line, (list, tuple, set)):
            self._fd.write(line + LF)
        else:
            self._fd.writelines([i + LF for i in line])

    def _w_head(self):
        self._wl('# Generated by {}'.format(sys.argv[0]) + LF)

    def _w_dict(self, data: dict, name: str, dict_comment='', keys_comments=None):
        keys_comments = keys_comments or {}
        dict_comment = '  # {}'.format(dict_comment) if dict_comment else ''
        if data:
            self._wl('{} = {{{}'.format(name, dict_comment))
        else:
            self._wl(['{} = {{}}{}'.format(name, dict_comment), ''])
            return
        old_comment = ''
        for key, val in data.items():
            new_comment = keys_comments.get(key, '')
            if new_comment and new_comment != old_comment:
                old_comment = new_comment
                self._wl('    # {}'.format(new_comment))
            self._wl('    {}: {},'.format(repr(key), repr(val) if val is not None else val))
        self._wl('}')

    def write_new(self, data: dict, comments=None):
        dict_comments = {}
        dicts = get_old(self._file, HEADER_DICTS.keys())
        for old in [x for x in dicts.keys()]:
            if not dicts[old]:
                dicts[old] = HEADER_DICTS[old]
                dict_comments[old] = 'missing, received from ru.py'
        dict_comments['_LNG'] = 'google translate - it\'s a good idea!'
        self._writter(data, dicts, False, dict_comments, comments)

    def write_gen(self, data: dict):
        self._writter(data, HEADER_DICTS, True, {})

    def _writter(self, data: dict, dicts: dict, gen: bool, dict_comments: dict, comments=None):
        with open(self._file, encoding='utf8', mode='w') as self._fd:
            self._w_head()
            if gen:
                self._wl([HEADER_1, '', ''])
            [self._w_dict(val, key, dict_comments.get(key, '')) or self._wl('') for key, val in dicts.items()]
            if gen:
                comments = {key: make_txt_comment(val) for key, val in data.items()}
                data = {key: ASSIGNS.get(key, None) for key in data}
            self._w_dict(data, '_LNG', dict_comments.get('_LNG', ''), comments)
        print('Saved to {}'.format(self._file))


def border():
    print('=' * 16)


def walking():
    def _walk(top_path, top_name='', subdir=(), no_files=()):
        dirs = []
        for k in os.listdir(top_path):
            if k.startswith(('__', '.')):
                continue
            path = os.path.join(top_path, k)
            name = '/'.join((top_name, k)) if top_name else k
            if os.path.isfile(path):
                if os.path.splitext(path)[1] == EXT and not (no_files and k in no_files):
                    yield path, name
            elif os.path.isdir and (not subdir or k in subdir):
                dirs.append((path, name))
        for path, name in dirs:
            yield from _walk(path, name)
    yield from _walk(SRC_DIR, subdir=WALK_SUBDIR, no_files=TOP_IGNORE)


def make_txt_comment(val: list) -> str:
    calls = OrderedDict()
    for v in val:
        if v['file'] not in calls:
            calls[v['file']] = OrderedDict()
        calls[v['file']][str(v['line'])] = None
    return ' '.join('{}#L{}'.format(k, ';#L'.join(v.keys())) for k, v in calls.items())


def check_diff(result: dict, old: dict) -> bool:
    def _diff(x, y):
        return [repr(k) for k in x if k not in y]

    def _print(data: list):
        print('  ' + ('{}  '.format(LF) if len(data) < 25 else '; ').join(data))

    add, del_ = _diff(result, old), _diff(old, result)
    if not (add or del_):
        print('No change in {}'.format(DST_FILE))
        return False
    print('File {} change:'.format(DST_FILE))
    if add:
        print(' New phrases ({}):'.format(len(add)))
        _print(add)
    if del_:
        print(' Deleted phrases ({}):'.format(len(del_)))
        _print(del_)
    return True


def get_old(file=DST_FILE, keys=('_LNG',)) -> dict:
    try:
        spec = importlib.util.spec_from_file_location("module.name", file)
        foo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(foo)
        # noinspection PyProtectedMember
        return getattr(foo, keys[0]) if len(keys) < 2 else {key: getattr(foo, key, {}) for key in keys}
    except Exception as e:
        print('Error loading {}: {}'.format(file, e))
        return {} if len(keys) < 2 else {key: {} for key in keys}


def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only-changes', action='store_true', help='Don\'t save file if _LANG unchanged')
    parser.add_argument('-gt', type=str, default='', metavar='[LNG]',
                        help='Use google translate to translate ru.py to another language')
    parser.add_argument('--no-gt', action='store_true', help='Don\'t translate, save direct')
    parser.add_argument('-d', type=float, default=3, metavar='[sec]',
                        help='Requests delay. Google may banned your client IP address.')
    parser.add_argument('-p', type=str, default='', help='http proxy, for gt')
    return parser.parse_args()


def version_warning():
    if sys.version_info[:2] < (3, 6):
        print('WARNING! This program may incorrect work in python < 3.6. You use {}'.format(
            '.'.join(list(map(str, sys.version_info[:3])))
        ))


def _fix_gt(origin: str, text: str) -> str:
    # gt теряет пробелы
    start, end = 0, 0
    for el in origin:
        if el != ' ':
            break
        start += 1
    for el in origin[::-1]:
        if el != ' ':
            break
        end += 1
    return ' ' * start + text.strip(' ') + ' ' * end


def google_translator(lang, delay, proxies, data: dict, chunk=30) -> dict:
    def progress(percent, eta):
        print('[{}%] ETA: {} sec, Elapse: {} sec.{}'.format(
            round(percent, 1), int(eta), int(time.time() - start_time), ' ' * 20), end='', flush=True
        )
    chunks = [x for x in data.keys()]
    chunks = [chunks[i:i + chunk] for i in range(0, len(chunks), chunk)]
    full = len(chunks)
    count, drift = 0, 0
    start_time = time.time()
    translator = googletrans.Translator(proxies=proxies)
    for part in chunks:
        print(end='\r', flush=True)
        progress((100 / full) * count, (full - count) * (delay + drift))
        drift = time.time()
        for trans in translator.translate(text=part, src='ru', dest=lang):
            data[trans.origin] = _fix_gt(trans.origin, trans.text)
        drift = time.time() - drift
        time.sleep(delay)
        count += 1
    print(end='\r', flush=True)
    progress(100, 0)
    print()
    return data


def main_trans(lang, delay, proxies, direct):
    if lang not in googletrans.LANGUAGES:
        print('Wrong lang code {}, use: {}'.format(
            lang, ', '.join([key for key in googletrans.LANGUAGES if key != 'ru'])))
        exit(1)
    if lang == 'ru':
        print('Translate ru to ru? What?')
        exit(1)
    data = get_old()
    proxies = {'http': proxies} if proxies else None
    if not data:
        print('Nope.')
        return
    border()
    if not direct:
        print('Translate from {} to {}'.format(googletrans.LANGUAGES['ru'], googletrans.LANGUAGES[lang]))
        print()
        data = google_translator(lang, delay, proxies, data)
        border()
    for key, val in data.items():
        if not (isinstance(val, str) or val is None):
            print('Wrong val type, {}, in key={}, set None'.format(repr(type(val)), repr(key)))
            data[key] = None
    border()
    file_path = os.path.join(LNG_DIR, 'gt_{}.py'.format(lang))
    Writter(file_path).write_new(data, read_lng_comments(data))
    print('Check {} before using'.format(file_path))


def main_gen(only_changes):
    parser = Parser()
    sum_time = time.time()
    sum_parse = len([parser.parse(path, name) for path, name in walking()])
    sum_time = time.time() - sum_time
    print()
    print('Parse {} files in {} sec'.format(sum_parse, sum_time))
    border()
    pop_count = 1
    call_count, unique_count = 0, 0
    for k, v in parser.result.items():
        unique_count += 1
        call_count += len(v)
        if len(v) > pop_count:
            pop_count = len(v)
    print('Summary: {} calls, {} phrases'.format(call_count, unique_count))
    if pop_count > 1:
        print('The most popular strings({} calls)'.format(pop_count))
        for k, v in parser.result.items():
            if len(v) == pop_count:
                print('  # {}'.format(make_txt_comment(v)))
                print('  {}'.format(repr(k)))
    border()
    change = check_diff(parser.result, get_old())
    if not only_changes or change:
        border()
        Writter(DST_FILE).write_gen(parser.result)
    print()


def main():
    version_warning()
    args = cli()
    if args.gt:
        main_trans(args.gt, args.d, args.p, bool(vars(args).get('no_gt')))
    else:
        main_gen(bool(vars(args).get('only_changes')))


if __name__ == '__main__':
    main()
