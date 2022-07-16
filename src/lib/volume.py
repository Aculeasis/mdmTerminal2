from utils import Popen

AMIXER = 'amixer'
SET = 'sset'
GET = 'sget'
QUOTE = '\''
UNDEFINED = 'undefined'

BEST = ('Line Out', 'Lineout volume control')
WORST = ('PCM', 'line', 'out')


def extract_volume_control():
    for card in range(_card_count()):
        control = _extract_volume_control(card)
        if control != UNDEFINED:
            return card, control
    return -1, UNDEFINED


def _extract_volume_control(card):
    try:
        data = _extract_values([AMIXER, 'scontents', '-c', str(card)])
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


def _card_count() -> int:
    count = 0
    try:
        for line in Popen(['aplay', '-l']).run().strip('\n').split('\n'):
            if line.startswith('card '):
                count += 1
    except RuntimeError:
        pass
    return count or 1


def set_volume(volume: int, control, card=0) -> int:
    volume = volume if isinstance(volume, int) else clean_volume(volume)
    p_volume = '{}%'.format(volume)

    control = '{0}{1}{0}'.format(QUOTE, control)
    return _extract_system_volume([AMIXER, '-c', str(card), SET, control, p_volume])


def get_volume(control, card=0) -> int:
    try:
        return _extract_system_volume([AMIXER, '-c', str(card), GET, control])
    except RuntimeError:
        return -1


def _extract_system_volume(cmd: list) -> int:
    data = _extract_values(cmd, '[', ']')
    for line in data:
        try:
            volume = clean_volume(line.replace('%', ''))
        except RuntimeError:
            continue
        return volume
    raise RuntimeError('Volume value not found')


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


def clean_volume(volume) -> int:
    try:
        volume = int(volume)
        if volume > 100 or volume < 0:
            raise ValueError('Wrong value, must be 0..100')
    except (TypeError, ValueError) as e:
        raise RuntimeError(e)
    return volume
