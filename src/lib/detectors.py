import pathlib

import utils
from lib.audio_utils import SnowboyHWD, PorcupineHWD, ModuleLoader, porcupine_lib


class Detector:
    # Имя детектора
    NAME = None
    # Ссылка на класс lib.audio_utils.Detector или lib.audio_utils.StreamDetector
    DETECTOR = None
    # Расширение генерируемых моделей
    MODELS_EXT = ''
    # Список расширений всех поддерживаемых моделей
    MODELS_SUPPORT = tuple()
    # Количество семплов доступных для записи
    SAMPLES_COUNT = 0
    # Минимальное количество семплов для тренинга, если ничего то = SAMPLES_COUNT
    _SAMPLES_TRAINING = None
    # Разрешить запись семплов
    ALLOW_RECORD = False
    # Разрешить создание новых моделей
    ALLOW_TRAINING = False
    # Детектор надо загрузить через ModuleLoader перед использованием
    MUST_PRELOAD = True
    # Поиск файлов-моделей не выполняется, вместо этого список читается из [models] в settings.ini
    FAKE_MODELS = False

    def __init__(self, home: str):
        self.path = str(pathlib.Path(home, 'detectors', str(self.NAME)))

    @property
    def SAMPLES_TRAINING(self):
        return self._SAMPLES_TRAINING or self.SAMPLES_COUNT

    def is_model_name(self, filename: str) -> bool:
        return utils.is_valid_base_filename(filename) and \
               pathlib.Path(filename).suffix.lstrip('.').lower() in self.MODELS_SUPPORT

    def gen_name(self, *args: str) -> str:
        return '.'.join([''.join(args), self.MODELS_EXT])

    def good_sample(self, sample: str or int) -> bool:
        if not isinstance(sample, (str, int)):
            return False
        try:
            return 0 < int(sample) <= self.SAMPLES_COUNT
        except ValueError:
            return False

    def __str__(self, *args, **kwargs):
        return str(self.NAME).capitalize()


class DetectorSnowboy(Detector):
    NAME = 'snowboy'
    DETECTOR = SnowboyHWD
    MODELS_EXT = 'pmdl'
    MODELS_SUPPORT = ('pmdl', 'umdl')
    SAMPLES_COUNT = 3
    ALLOW_RECORD = True
    ALLOW_TRAINING = True


class DetectorPorcupine(Detector):
    NAME = 'porcupine'
    DETECTOR = PorcupineHWD
    MODELS_EXT = 'ppn'
    MODELS_SUPPORT = ('ppn',)


DETECTORS = {target.NAME: target for target in Detector.__subclasses__()}


def detector(name, home: str or None) -> Detector:
    cls = DETECTORS.get(name, Detector)
    return cls(home) if home is not None else cls


def reset_detector_caches():
    ModuleLoader().clear()
    for x in list(DETECTORS.values()):
        try:
            x.reset()
        except (TypeError, AttributeError):
            pass


def porcupine_select_auto(home: str) -> bool:
    home = pathlib.Path(detector('porcupine', home).path)
    model_file = 'porcupine_params.pv'
    library = porcupine_lib()

    if not home.is_dir():
        return False
    if not (home / library).is_file():
        raise RuntimeError('library missing: {}'.format(library))
    if not (home / model_file).is_file():
        raise RuntimeError('model file missing: {}'.format(model_file))
    return True
