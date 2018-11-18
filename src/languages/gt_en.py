
CONFIG = {
    'err_ya_key': 'Error getting key for Yandex: {}',
    'models_count_call': 'Loaded {} models',
    'load_for': 'Loaded {} options in {}',
    'load': 'Configuration loaded!',
    'lng_load_for': 'Localization {} loaded for {}',
}

LOADER = {
    'hello': 'Greetings. The voice terminal Majordomo is configured, three ... two ... one ...',
    'bye': 'The voice terminal majordomo completes its work.',
}
LOGGER = {}
MODULES = {
    # lock
    'lock_name': 'Блокировка',
    'lock_dsc': 'Включение/выключение блокировки терминала',
    'lock_phrase_lock': 'блокировка',
    #
    'lock_say_unlock': 'Блокировка снята',
    'lock_say_lock': 'Блокировка включена',
    # debug
    'debug_name': 'Debugging',
    'debug_dsc': 'Setup and Debug Mode',
    'debug_phrase_enter': 'developer mode',
    'debug_phrase_exit': 'exit',
    #
    'debug_say_exit': 'Attention! Exit developer mode',
    'debug_say_enter': 'Attention! Developer mode is enabled. To return to normal mode, say \'exit\'',
}
MODULES_MANAGER = {}

MPD_CONTROL = {'err_mpd': 'Error connecting to the MPD server'}

PLAYER = {}
SERVER = {}
STTS = {
    'tts_lng_def': 'en-US',
    'tts_lng_dict': {'google': 'en', 'yandex': 'en-US'},
    'stt_lng': 'en-US',

    # Phrases
    'p_hello': ['Hello', 'Listening', 'In touch', 'Hi Hi'],
    'p_deaf': ['I have not heard anything', 'You did not say anything', 'Can not hear anything', 'I did not get that'],
    'p_ask': ['Can\'t hear anything, repeat your request.'],
}
TERMINAL = {}

YANDEX_EMOTION = {
    'good'    : 'good',
    'neutral' : 'neutral',
    'evil'    : 'evil',
}

YANDEX_SPEAKER = {
    'jane'  : 'Jane',
    'oksana': 'Oksana',
    'alyss' : 'Alyss',
    'omazh' : 'Omazh',
    'zahar' : 'Zahar',
    'ermil' : 'Ermil'
}

RHVOICE_SPEAKER = {
    'alan': 'Alan',
    'bdl': 'bdl',
    'clb': 'clb',
    'slt': 'slt',
    'anna' : 'Anna'
}
