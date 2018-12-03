from utils import Popen

AMIXER = 'amixer'
DEVICES = [AMIXER, 'scontrols']
SET = [AMIXER, 'sset']
QUOTE = '\''
UNDEFINED = 'undefined'

BEST = ('Line Out', 'Lineout volume control')
WORST = ('line', 'out')


def extract_volume():
    data = []
    try:
        for line in Popen(DEVICES).run().strip('\n').split('\n'):
            start = line.find(QUOTE)
            if start > -1:
                start += 1
                end = line[start:].find(QUOTE)
                if end > -1:
                    end += start
                    data.append(line[start:end])
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


def set_volume(volume, control):
    try:
        volume = int(volume)
        if volume > 100 or volume < 0:
            raise ValueError('Wrong value, must be 0..100')
        p_volume = '{}%'.format(volume)
    except (TypeError, ValueError) as e:
        raise RuntimeError(e)
    control = '{0}{1}{0}'.format(QUOTE, control)
    cmd = SET.copy()
    cmd.extend([control, p_volume])
    Popen(cmd).run()
    return volume
