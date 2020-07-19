import pathlib
import platform

import utils


class Detector:
    # Имя детектора
    NAME = None
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
    MODELS_EXT = 'pmdl'
    MODELS_SUPPORT = ('pmdl', 'umdl')
    SAMPLES_COUNT = 3
    ALLOW_RECORD = True
    ALLOW_TRAINING = True


class DetectorPorcupine(Detector):
    NAME = 'porcupine'
    MODELS_EXT = 'ppn'
    MODELS_SUPPORT = ('ppn',)
    SAMPLES_COUNT = 0
    ALLOW_RECORD = False
    ALLOW_TRAINING = False


DETECTORS = {
    DetectorSnowboy.NAME: DetectorSnowboy,
    DetectorPorcupine.NAME: DetectorPorcupine,
}


def detector(name=None) -> Detector:
    return DETECTORS.get(name, Detector)()


def porcupine_lib() -> str:
    ext = {'windows': 'dll', 'linux': 'so', 'darwin': 'dylib'}
    return 'libpv_porcupine.{}'.format(ext.get(platform.system().lower(), 'linux'))


def porcupine_select_auto(home: str) -> bool:
    home = pathlib.Path(home, 'porcupine')
    model_file = 'porcupine_params.pv'
    library = porcupine_lib()

    if not home.is_dir():
        return False
    if not (home / library).is_file():
        raise RuntimeError('library missing: {}'.format(library))
    if not (home / model_file).is_file():
        raise RuntimeError('model file missing: {}'.format(model_file))
    return True
