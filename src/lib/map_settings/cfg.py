from lib import STT
from lib import TTS
from lib.polly_signing import AWS_REGIONS
from lib.snowboy_training import Training

VAD_MODE = ['snowboy', 'webrtc', 'apm', 'energy']
VAD_LVL = [0, 1, 2, 3]
LOG_LVL = ['debug', 'info', 'warn', 'error', 'crit']
_0_100 = list(range(101))
RHVoice = ['anna', 'elena', 'irina', 'aleksandr']


INTERFACES = {
    'Настройки': ('settings', 'listener', 'smarthome', 'proxy', 'music'),
    'Выбор и настройка голосовых сервисов': (
        'noise_suppression', 'snowboy', 'yandex',
        'aws', 'azure', 'rhvoice-rest', 'rhvoice',
        'pocketsphinx-rest'
    ),
    'Запись ключевого слова': ('persons',),
    'Обслуживание': ('update', 'plugins', 'cache', 'log')
}

CFG_DSC = {
    'settings': {
        'providertts' : {
            'name': 'Провайдер синтеза речи',
            'options': TTS.PROVIDERS,
        },
        'providerstt' : {
            'name': 'Провайдер распознавания речи',
            'options': STT.PROVIDERS,
        },
        'ip' : {
            'name': 'IP терминала',
        },
        'sensitivity' : {
            'name': '',
        },
        'alarmkwactivated': {
            'name': '',
        },
        'alarmtts': {
            'name': '',
        },
        'alarmstt': {
            'name': '',
        },
        'alarm_recognized': {
            'name': '',
        },
        'first_love': {
            'name': '',
        },
        'last_love': {
            'name': '',
        },
        'mic_index': {
            'name': ''
        },
        'optimistic_nonblock_tts': {
            'name': '',
        },
        'ask_me_again': {
            'name': ''
        },
        'quiet': {
            'name': '',
        },
        'no_hello': {
            'name': '',
        },
        'blocking_listener': {
            'name': '',
        },
        'audio_gain': {
            'name': ''
        },
        'phrase_time_limit': {
            'name': ''
        },
        'no_background_play': {
            'name': '',
        },
        'chrome_mode': {
            'name': '',
        },
        'chrome_choke': {
            'name': '',
        },
        'chrome_alarmstt': {
            'name': '',
        },
        'lang': {
            'name': ''
        },
        'lang_check': {
            'name': '',
        },
        'software_player': {
            'name': ''
        },
        'lazy_record': {
            'name': '',
        },
    },
    'listener': {
        'stream_recognition': {
            'name': '',
        },
        'vad_mode': {
            'name': '',
            'options': VAD_MODE,
        },
        'vad_chrome': {
            'name': '',
            'options': VAD_MODE,
        },
        'vad_lvl': {
            'name': '',
            'options': VAD_LVL,
        },
        'energy_lvl': {
            'name': ''
        },
        'energy_dynamic': {
            'name': '',
        },
        'silent_multiplier': {
            'name': ''
        },
        'no_listen_music': {
            'name': '',
        },
    },
    'smarthome': {
        'ip': {
            'name': ''
        },
        'outgoing_socket': {
            'name': ''
        },
        'token': {
            'name': ''
        },
        'terminal': {
            'name': ''
        },
        'username': {
            'name': ''
        },
        'password': {
            'name': ''
        },
        'object_name': {
            'name': ''
        },
        'object_method': {
            'name': ''
        },
        'heartbeat_timeout': {
            'name': ''
        },
        'disable_http': {
            'name': '',
        },
        'disable_server': {
            'name': '',
        },
    },
    'music': {
        'control': {
            'name': '',
        },
        'type': {
            'name': '',
            'options': ['mpd', 'lms'],
        },
        'ip': {
            'name': ''
        },
        'port': {
            'name': ''
        },
        'username': {
            'name': ''
        },
        'password': {
            'name': ''
        },
        'pause': {
            'name': '',
        },
        'smoothly': {
            'name': '',
        },
        'quieter': {
            'name': ''
        },
        'wait_resume': {
            'name': ''
        },
        'lms_player': {
            'name': ''
        },
    },
    'log': {
        'file_lvl' : {
            'name': '',
            'options': LOG_LVL,
        },
        'print_lvl': {
            'name': '',
            'options': LOG_LVL,
        },
        'remote_log': {
            'name': '',
        },
        'print_ms': {
            'name': '',
        },
        'method': {
            'name': '',
            'options': [1, 2, 3],
        },
        'file': {
            'name': '',
        },
    },
    'yandex': {
        'api': {
            'name': '',
            'options': [1, 2],
        },
        'emotion': {
            'name': '',
            'options': ['good', 'neutral', 'evil'],
        },
        'speaker': {
            'name': '',
            'options': ['jane', 'oksana', 'alyss', 'omazh', 'zahar', 'ermil'],
        },
        'speed': {
            'name': '',
        },
        'grpc': {
            'name': '',
        },
    },
    'google': {
        'slow': {
            'name': '',
        },
    },
    'aws': {
        'speaker': {
            'name': '',
            'options': ['Tatyana', 'Maxim']
        },
        'access_key_id': {
            'name': ''
        },
        'secret_access_key': {
            'name': '',
        },
        'region': {
            'name': '',
            'options': AWS_REGIONS,
        },
        'boto3': {
            'name': '',
        },
    },
    'rhvoice-rest': {
        'server': {
            'name': ''
        },
        'speaker': {
            'name': '',
            'options': RHVoice
        },
        'rate': {
            'name': '',
            'options': _0_100,
        },
        'pitch': {
            'name': '',
            'options': _0_100,
        },
        'volume': {
            'name': '',
            'options': _0_100,
        },
    },
    'rhvoice': {
        'speaker': {
            'name': '',
            'options': RHVoice
        },
    },
    'pocketsphinx-rest': {
        'server': {
            'name': ''
        },
    },
    'azure': {
        'speaker': {
            'name': ''
        },
        'region': {
            'name': ''
        },
    },
    'cache': {
        'tts_priority': {
            'name': '',
            'options': lambda: ['', '*'] + list(TTS.PROVIDERS.keys())
        },
        'tts_size': {
            'name': '',
        },
        'path': {
            'name': '',
        },
    },
    'models': {
        'allow': {
            'name': '',
        }
    },
    'persons': {},
    'proxy': {
        'enable': {
            'name': '',
        },
        'monkey_patching': {
            'name': '',
        },
        'proxy': {
            'name': '',
        }
    },
    'snowboy': {
        'clear_models': {
            'name': '',
        },
        'token': {
            'name': '',
        },
        'name': {
            'name': '',
        },
        'age_group': {
            'name': '',
            'options': Training.PARAMS2['age_group'][0]
        },
        'gender': {
            'name': '',
            'options': Training.PARAMS2['gender'][0]
        },
        'microphone': {
            'name': '',
        },
    },
    'update': {
        'interval': {
            'name': ''
        },
        'pip': {
            'name': '',
        },
        'apt': {
            'name': '',
        },
        'turnoff': {
            'name': '',
            'options': [-1, 0, 1]
        },
        'fallback': {
            'name': '',
        },
    },
    'noise_suppression': {
        'snowboy_apply_frontend': {
            'name': '',
        },
        'enable': {
            'name': '',
        },
        'conservative': {
            'name': '',
        },
        'ns_lvl': {
            'name': '',
            'options': VAD_LVL,
        },
    },
    'plugins': {
        'enable': {
            'name': '',
        },
        'whitelist': {
            'name': '',
        },
        'blacklist': {
            'name': '',
        },
        'blacklist_on_failure': {
            'name': '',
        },
    },
}
