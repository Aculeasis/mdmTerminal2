from utils import Popen

AMIXER = 'amixer'
DEVICES = [AMIXER, 'scontrols']
SET = 'sset'
GET = 'sget'
QUOTE = '\''
UNDEFINED = 'undefined'

BEST = ('Line Out', 'Lineout volume control')
WORST = ('line', 'out')


def extract_volume_control():
    try:
        data = _extract_values(DEVICES)
    except RuntimeError:
        return UNDEFINED
    # find best
    for line in data:
        if line in BEST:
            return line
    # find worst :(
    for line in data:
        line_low = line.lower()
        for test in WORST:
            if line_low.find(test) == -1:
                line = None
                break
        if line:
            return line
    return UNDEFINED


def set_volume(volume, control) -> int:
    volume = _clean_volume(volume)
    p_volume = '{}%'.format(volume)

    control = '{0}{1}{0}'.format(QUOTE, control)
    Popen([AMIXER, SET, control, p_volume]).run()
    return volume


def get_volume(control) -> int:
    try:
        data = _extract_values([AMIXER, GET, control], '[', ']')
    except RuntimeError:
        return -1
    for line in data:
        try:
            volume = _clean_volume(line.replace('%', ''))
        except RuntimeError:
            continue
        return volume
    return -1


def _extract_values(cmd: list, sep_start=QUOTE, sep_end=QUOTE) -> list:
    data = []
    for line in Popen(cmd).run().strip('\n').split('\n'):
        start = line.find(sep_start)
        if start > -1:
            start += 1
            end = line[start:].find(sep_end)
            if end > -1:
                end += start
                data.append(line[start:end])
    return data


def _clean_volume(volume) -> int:
    try:
        volume = int(volume)
        if volume > 100 or volume < 0:
            raise ValueError('Wrong value, must be 0..100')
    except (TypeError, ValueError) as e:
        raise RuntimeError(e)
    return volume
