
SETTINGS_TESTER = {
    # Если кинет исключение, вернет строку или False - плохая настройка, игнорируем ее.
    # TODO: Больше проверок
    'settings' : {
        'audio_gain': lambda x: min_max(x, 0.1, 10),
        'sensitivity': lambda x: min_max(x, 0.0, 1),
        'mic_index': lambda x: min_max(x, min_=-1),
        'ask_me_again': lambda x: min_max(x, min_=0),
        'phrase_time_limit': lambda x: min_max(x, min_=1),
        'silent_multiplier': lambda x: min_max(x, 0.1, 5.0),
    },
    'listener': {
        'vad_lvl': lambda x: min_max(x, 1, 3),
        'speech_timeout': lambda x: min_max(x, min_=0),
    },
    'smarthome': {
        'heartbeat_timeout': lambda x: min_max(x, min_=0),
        'pool_size': lambda x: min_max(x, min_=0),
    },
    'log': {
        'method': lambda x: min_max(x, 0, 3),
    },
    'yandex': {
        'api': lambda x: min_max(x, 1, 3),
    },
}


def min_max(val, min_=None, max_=None):
    def less():
        return 'less or {}'.format(max_)

    def more():
        return 'more or {}'.format(min_)
    msg = 'Must be'

    if min_ is None and max_ is None:
        raise RuntimeError('min == max == None')
    elif min_ is None:
        return None if val <= max_ else '{} {}'.format(msg, less())
    elif max_ is None:
        return None if min_ <= val else '{} {}'.format(msg, more())
    return None if min_ <= val <= max_ else '{} {} and {}'.format(msg, more(), less())
