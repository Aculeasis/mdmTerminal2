CFG = {  # Дефолтные настройки https://github.com/Aculeasis/mdmTerminal2/wiki/settings.ini
    'settings': {
        'providertts'     : 'google',
        'providerstt'     : 'google',
        'ip'              : '',
        'sensitivity'     : 0.45,
        'alarmkwactivated': True,
        'alarmtts'        : True,
        'alarmstt'        : True,
        'alarm_recognized': False,
        'first_love'      : True,
        'last_love'       : False,
        'mic_index'   : -1,
        'optimistic_nonblock_tts': True,
        'ask_me_again': 0,
        'quiet': False,
        'no_hello': False,
        'blocking_listener': True,
        'say_stt_error': False,
        'audio_gain': 1.0,
        'phrase_time_limit': 12,
        'no_background_play': False,
        'chrome_mode': True,
        'chrome_choke': False,
        'chrome_alarmstt': False,
        'lang': 'ru',
        'lang_check': False,
        'software_player': '',
        'lazy_record': False,
    },
    'listener': {
        'detector': '',
        'stream_recognition': True,
        'vad_mode': 'snowboy',
        'vad_chrome': '',
        'vad_lvl': 0,
        'energy_lvl': 0,
        'energy_dynamic': True,
        'silent_multiplier': 1.0,
        'speech_timeout': 3,
        'no_listen_music': False,
    },
    'smarthome': {
        'ip': '',
        'outgoing_socket': '',
        'token': '',
        'terminal': '',
        'username': '',
        'password': '',
        'object_name': '',
        'object_method': '',
        'heartbeat_timeout': 0,
        'pool_size': 1,
        'allow_addresses': '',
        'disable_http': False,
        'disable_server': False,
        'unsafe_rpc': False,
        'send_rms': False,
        'async_notify': True,
    },
    'music': {
        'control': True,
        'type': 'mpd',
        'ip': '127.0.0.1',
        'port': 6600,
        'username': '',
        'password': '',
        'pause': True,
        'smoothly': False,
        'quieter': 0,
        'wait_resume': 5,
        'lms_player': '',
        'ignore_events': '',
    },
    'log': {
        'file_lvl' : 'debug',
        'print_lvl': 'debug',
        'remote_log': True,
        'print_ms': True,
        'method': 3,
        'file': '',
    },
    'yandex': {
        'api': 1,
        'emotion': 'good',
        'speaker': 'alyss',
        'speed': 1.0,
        'grpc': False,
    },
    'google': {
        'slow': False,
    },
    'aws': {
        'speaker': 'Tatyana',
        'access_key_id': '',
        'secret_access_key': '',
        'region': 'eu-central-1',
        'boto3': False,
    },
    'rhvoice-rest': {
        'server': 'http://127.0.0.1:8080',
        'speaker': 'anna',
        'rate': 50,
        'pitch': 50,
        'volume': 50,
    },
    'rhvoice': {
        'speaker': 'anna',
    },
    'pocketsphinx-rest': {
        'server': 'http://127.0.0.1:8085',
    },
    'vosk-rest': {
        'server': 'http://127.0.0.1:8086',
    },
    'azure': {
        'speaker': 'EkaterinaRUS',
        'region': 'westus',
    },
    'cache': {
        'tts_priority': '',
        'tts_size': 100,
        'path': '',
    },
    'models': {
        'allow': ''
    },
    'persons': {},
    'proxy': {
        'enable': 0,
        'monkey_patching': True,
        'proxy': 'socks5h://127.0.0.1:9050'
    },
    'snowboy': {
        'url': 'https://snowboy.kitt.ai/api/v1/train/',
        'clear_models': False,
        'token': 'd4977cf8ff6ede6efb8d2277c1608c7dbebf18a7',
        'name': 'unknown',
        'age_group': '30_39',
        'gender': 'M',
        'microphone': 'mic',
    },
    'update': {
        'interval': 0,
        'pip': True,
        'apt': False,
        'turnoff': -1,
        'fallback': True,
    },
    'backup': {
        'interval': 0,
        'max_count': 3,
    },
    'volume': {
        'card': 0,
        'line_out': '',
        'changes_quiet': False,
    },
    'noise_suppression': {
        'snowboy_apply_frontend': False,
        'enable': False,
        'conservative': False,
        'ns_lvl': 0,
    },
    'plugins': {
        'enable': True,
        'whitelist': '',
        'blacklist': '',
        'blacklist_on_failure': False,
    },
    'system': {
        'ws_token': 'token_is_unset',
    }
}

STATE = {
    'system': {
        'ini_version': 54,
        'merge': 1,
        'PLUGINS_API': 3,
        'VERSION': (0, 18, 10),
    }
}
