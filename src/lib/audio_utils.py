import audioop
import collections
import os
import platform
import threading
import time
from functools import lru_cache

from speech_recognition import Microphone, AudioData

from utils import singleton, is_int, RecognitionCrashMessage


# VAD
def _loader_apm():
    # noinspection PyUnresolvedReferences
    from webrtc_audio_processing import AudioProcessingModule
    return AudioProcessingModule


def _loader_webrtc():
    from webrtcvad import Vad
    return Vad


# HWD
def _loader_snowboy():
    from lib import snowboydetect
    return snowboydetect.SnowboyDetect


def _loader_porcupine():
    import struct
    from lib.porcupine import Porcupine as Porcupine_

    class Porcupine(Porcupine_):
        def process(self, pcm: bytes) -> int:
            result = super().process(struct.unpack('H' * (len(pcm) // 2), pcm))
            if self._num_keywords == 1:
                result = int(result) - 1
            return -2 if result < 0 else result + 1

        def __del__(self):
            if hasattr(self, '_delete_func'):
                self.delete()

    return Porcupine


def porcupine_lib() -> str:
    ext = {'windows': 'dll', 'linux': 'so', 'darwin': 'dylib'}
    return 'libpv_porcupine.{}'.format(ext.get(platform.system().lower(), 'linux'))


@singleton
class ModuleLoader:
    def __init__(self):
        # apm, webrtc, snowboy, porcupine
        self._loaded = dict()
        self._try = set()
        self._error_msg = list()
        self._lock = threading.Lock()

    def clear(self):
        with self._lock:
            self._loaded.clear()
            self._try.clear()
            self._error_msg.clear()

    def is_loaded(self, name: str) -> bool:
        if name not in self._try:
            with self._lock:
                self._loader(name)
                self._try.add(name)
        return name in self._loaded

    def _loader(self, name: str):
        callback = '_loader_{}'.format(name)
        try:
            module = globals()[callback]()
            if not module:
                raise ValueError('Internal error - wrong return')
        except Exception as e:
            self._error_msg.append('Error loading {}, {}: {}'.format(name, type(e).__name__, e))
        else:
            self._loaded[name] = module

    def get(self, name: str):
        try:
            return self._loaded[name]
        except KeyError:
            raise RuntimeError('Getting module {} before loading!'.format(name))

    def extract_errors(self) -> tuple:
        if self._error_msg:
            try:
                return tuple(self._error_msg)
            finally:
                self._error_msg.clear()
        return ()


class RMS:
    WRONG_RMS = 32768

    def __init__(self, width):
        self._width = width
        self.min, self.max = -1, -1
        self._frames, self._rms_sum = 0, 0

    def measure(self, fragment):
        self.calc(audioop.rms(fragment, self._width))

    def calc(self, rms):
        if rms == self.WRONG_RMS:
            return
        if self.max == -1:
            self.min, self.max = rms, rms
        elif rms > self.max:
            self.max = rms
        elif rms < self.min:
            self.min = rms
        self._frames += 1
        self._rms_sum += rms

    def result(self) -> tuple or None:
        if not self._frames:
            return None
        return self.min, self.max, self._rms_sum // self._frames


@singleton
class APMSettings:
    NAME = 'apm'

    def __init__(self):
        self._cfg = {
            'enable': False,
            'conservative': False,
            'aec_type': 0,
            'agc_type': 0,
            'ns_lvl': 0,
            'aec_lvl': None,
            'agc_lvl': None,
            'agc_target': None,
        }

    def cfg(self, **kwargs):
        # https://github.com/xiongyihui/python-webrtc-audio-processing/blob/master/src/audio_processing_module.cpp
        # aec_type = 1..2, 0 - disable
        # agc_type = 1..2? 0 - disable
        # ns_lvl = 0..3
        # agc_lvl = 0..100, for agc_type == 2?
        # agc_target = 0..31, for agc_type == 1..2
        # aec_lvl = 0..2, for aec_type == 2?
        for key, val in kwargs.items():
            if key in ('enable', 'conservative'):
                if isinstance(val, bool):
                    self._cfg[key] = val
                continue
            val = self._to_int(val)
            if val is None:
                continue

            if key == 'ns_lvl':
                self._cfg[key] = min(3, max(0, val))
            elif key == 'agc_lvl':
                self._cfg[key] = min(100, max(0, val))
            elif key == 'agc_target':
                self._cfg[key] = min(31, max(0, val * -1 if val < 0 else val))
            elif key in ('aec_lvl', 'agc_type', 'aec_type'):
                self._cfg[key] = min(2, max(0, val))

    @property
    def enable(self):
        return self._cfg['enable'] and ModuleLoader().is_loaded(self.NAME)

    @property
    def conservative(self):
        return self._cfg['conservative']

    @property
    def instance(self):
        return self._constructor(**self._cfg)

    @staticmethod
    def _to_int(val):
        if isinstance(val, str):
            val = int(val) if is_int(val) else None
        elif not isinstance(val, int):
            val = None
        return val

    @lru_cache(maxsize=1)
    def _constructor(self, **kwargs):
        ap = ModuleLoader().get(self.NAME)(aec_type=kwargs['aec_type'], enable_ns=True, agc_type=kwargs['agc_type'])
        if kwargs['ns_lvl'] is not None:
            ap.set_ns_level(kwargs['ns_lvl'])
        if kwargs['aec_type'] and kwargs['aec_lvl'] is not None:
            ap.set_aec_level(kwargs['aec_lvl'])
        if kwargs['agc_type']:
            if kwargs['agc_lvl'] is not None:
                ap.set_agc_level(kwargs['agc_lvl'])
            if kwargs['agc_target'] is not None:
                ap.set_agc_target(kwargs['agc_target'])
        return ap


class MicrophoneStream(Microphone.MicrophoneStream):
    def deactivate(self):
        pass

    @staticmethod
    def reactivate(chunks):
        return chunks

    @property
    def read_available(self) -> int:
        return self.pyaudio_stream.get_read_available()


class MicrophoneStreamAPM(MicrophoneStream):
    def __init__(self, pyaudio_stream, width, rate, conservative):
        super().__init__(pyaudio_stream)
        self._ap = APMSettings().instance
        self._conservative = conservative
        self._ap.set_stream_format(rate, 1)
        self._buffer = b''
        self._sample_size = width * int(rate * 10 / 1000)
        self._active = True

    def read(self, size):
        data = super().read(size)
        return self._convert(data) if self._active else data

    def _convert(self, data):
        return b''.join(chunk for chunk in self._reader(data))

    def _reader(self, data: bytes):
        self._buffer += data
        buff_len = len(self._buffer)
        read_len = (buff_len // self._sample_size) * self._sample_size
        if read_len:
            for step in range(0, read_len, self._sample_size):
                yield self._ap.process_stream(self._buffer[step: step + self._sample_size])
            self._buffer = self._buffer[read_len:]

    def deactivate(self):
        if self._conservative:
            self._active = False

    def reactivate(self, chunks):
        if not self._active:
            self._active = True
            if self._buffer:
                raise RuntimeError('buffer {}'.format(len(self._buffer)))
            return collections.deque(self._convert(chunk) for chunk in chunks)
        return chunks


class BaseDetector:
    def __init__(self, duration, width, rate, resample_rate, rms, another=None):
        self._vad = another
        self._resample_rate = resample_rate
        self._sample_size = int(width * (self._resample_rate * duration / 1000)) if duration else None
        self._rate = None
        self._width = width
        self._rms = RMS(width) if rms and not another else None
        self._resample_state = None
        self._resampler = lambda x: x
        self._current_state = -2
        self._speech_state = False
        self._buffer = b''
        self.set_rate(rate)

        self._processing_chunk = self.new_chunk if self._sample_size is None else self._new_chunk
        self.one_vad = True

    def set_rate(self, rate: int):
        self._rate = rate
        self._resampler = lambda x: x if self._rate == self._resample_rate else self._audio_resampler
        self._vad and self._vad.set_rate(self._resample_rate)

    @property
    def energy_threshold(self):
        return self._vad.energy_threshold if self._vad else None

    def dynamic_energy(self):
        self._vad and self._vad.dynamic_energy()

    def rms(self) -> tuple or None:
        return self._vad and self._vad.rms() or self._rms and self._rms.result()

    def detect(self, buffer: bytes) -> int:
        buffer = self._resampler(buffer)
        self._vad and self._vad.is_speech(buffer)
        self._processing_chunk(buffer)
        return self._current_state

    def is_speech(self, buffer: bytes) -> bool:
        buffer = self._resampler(buffer)
        self._rms and self._rms.measure(buffer)
        if self._vad:
            self._speech_state = self._vad.is_speech(buffer)
        not (self._vad and self.one_vad) and self._processing_chunk(buffer, is_speech=True)
        return self._speech_state

    def new_chunk(self, buffer: bytes, is_speech=False):
        raise NotImplementedError

    def reset(self):
        raise NotImplementedError

    def die(self):
        raise NotImplementedError

    def _audio_resampler(self, buffer: bytes) -> bytes:
        buffer, self._resample_state = audioop.ratecv(
            buffer, self._width, 1, self._rate, self._resample_rate, self._resample_state
        )
        return buffer

    def _new_chunk(self, buffer: bytes, is_speech=False):
        self._buffer += buffer
        buff_len = len(self._buffer)
        read_len = (buff_len // self._sample_size) * self._sample_size
        if read_len:
            for step in range(0, read_len, self._sample_size):
                self.new_chunk(self._buffer[step: step + self._sample_size], is_speech)
            self._buffer = self._buffer[read_len:]


class Detector(BaseDetector):
    def die(self):
        pass

    @classmethod
    def reset(cls):
        cls._constructor.cache_clear()

    def new_chunk(self, buffer: bytes, is_speech=False):
        raise NotImplementedError

    @classmethod
    @lru_cache(maxsize=None)
    def _constructor(cls, *args, **kwargs):
        raise NotImplementedError


class SnowboyHWD(Detector):
    def __init__(self, home, hot_word_files, sensitivities, audio_gain, width, rate, another, apply_frontend, rms, **_):
        self._snowboy = SnowboyHWD._constructor(home, sensitivities, audio_gain, apply_frontend, *hot_word_files)
        super().__init__(150, width, rate, self._snowboy.SampleRate(), rms, another)
        self._processing_chunk = self.new_chunk

    def new_chunk(self, buffer: bytes, is_speech=False):
        self._buffer += buffer
        if len(self._buffer) >= self._sample_size:
            self._current_state = self._snowboy.RunDetection(self._buffer)
            if not self._vad:
                self._speech_state = self._current_state >= 0
            self._buffer = b''

    @classmethod
    @lru_cache(maxsize=1)
    def _constructor(cls, home, sensitivities, audio_gain, apply_frontend, *hot_word_files):
        return ModuleLoader().get('snowboy')(
            home=home, sensitivities=sensitivities, audio_gain=audio_gain,
            apply_frontend=apply_frontend, hot_word_files=hot_word_files,
        )


class PorcupineHWD(Detector):
    def __init__(self, home, hot_word_files, sensitivities, width, rate, another, rms, **_):
        self._porcupine = PorcupineHWD._constructor(home, sensitivities, *hot_word_files)
        super().__init__(1, width, rate, self._porcupine.sample_rate, rms, another)
        self._sample_size = width * self._porcupine.frame_length
        if not self._vad:
            raise RecognitionCrashMessage('PorcupineHWD without VAD. WTF?')

    def new_chunk(self, buffer: bytes, is_speech=False):
        self._current_state = self._porcupine.process(buffer)

    @classmethod
    @lru_cache(maxsize=1)
    def _constructor(cls, home, sensitivities, *hot_word_files):
        library_path = os.path.join(home, porcupine_lib())
        model_file_path = os.path.join(home, 'porcupine_params.pv')
        return ModuleLoader().get('porcupine')(
            library_path=library_path, model_file_path=model_file_path, keyword_file_paths=hot_word_files,
            sensitivities=sensitivities,
        )


class EmptyHWD(Detector):
    def __init__(self, width, rate, another, rms, **_):
        super().__init__(None, width, rate, rate, rms, another)
        if not self._vad:
            raise RecognitionCrashMessage('EmptyHWD without VAD. WTF?')

    def detect(self, buffer: bytes) -> int:
        if self._vad.is_speech(buffer):
            self._current_state = 1
        return self._current_state

    def new_chunk(self, buffer: bytes, is_speech=False):
        pass

    @classmethod
    def reset(cls):
        pass

    @classmethod
    @lru_cache(maxsize=None)
    def _constructor(cls, *args, **kwargs):
        pass


class WebRTCVAD(Detector):
    def __init__(self, width, rate, lvl, rms, **_):
        super().__init__(30, width, rate, 16000, rms)
        self._vad = WebRTCVAD._constructor(lvl)

    def new_chunk(self, buffer: bytes, is_speech=False):
        self._speech_state = self._vad.is_speech(buffer, self._resample_rate)

    @classmethod
    @lru_cache(maxsize=1)
    def _constructor(cls, lvl):
        return ModuleLoader().get('webrtc')(lvl)


class APMVAD(Detector):
    def __init__(self, width, rate, lvl, rms, **_):
        super().__init__(10, width, rate, 16000, rms)
        self._apm = APMVAD._constructor(lvl)

    def is_speech(self, buffer: bytes) -> bool:
        super().is_speech(buffer)
        return self._apm.has_voice()

    def new_chunk(self, buffer: bytes, is_speech=False):
        self._apm.process_stream(buffer)

    @classmethod
    @lru_cache(maxsize=1)
    def _constructor(cls, lvl):
        apm = ModuleLoader().get('apm')(enable_vad=True)
        apm.set_vad_level(lvl)
        return apm


class StreamDetector(BaseDetector):
    def __init__(self, width, rate, resample_rate, rms, another, **_):
        super().__init__(None, width, rate, resample_rate, rms, another)
        self.one_vad = False
        self.processing = True
        self.is_ok = False
        self.text = ''

    def reset(self):
        pass

    @property
    def model_info(self):
        raise NotImplementedError

    @property
    def recognition_time(self):
        return 0

    @property
    def record_time(self):
        return 0

    def new_chunk(self, buffer: bytes, is_speech=False):
        raise NotImplementedError

    def end(self):
        raise NotImplementedError

    def die(self):
        raise NotImplementedError


def reset_vad_caches():
    ModuleLoader().clear()
    WebRTCVAD.reset()
    APMVAD.reset()


class StreamRecognition(threading.Thread):
    def __init__(self, voice_recognition):
        super().__init__()
        self._time = TimeFusion()
        self._voice_recognition = voice_recognition
        self._pipe = None
        self.sample_rate = None
        self.sample_width = None
        self.work = True
        self._text = None
        self._written = False
        self._block = threading.Event()
        self.__event = threading.Event()

    @property
    def ready(self):
        return self._pipe is not None

    @property
    def is_ok(self):
        return self._written and self.ready

    @property
    def processing(self):
        return self._text is None

    def time_up(self):
        self._time.up()

    def end(self):
        self.time_up()
        if self.ready:
            self._pipe.append(b'')
            self.__event.set()

    def terminate(self):
        self.work = False
        self.end()

    def init(self, iterable=(), maxlen=None, sample_rate=None, sample_width=None):
        self._pipe = collections.deque(iterable, maxlen)
        self.sample_rate = sample_rate
        self.sample_width = sample_width
        self.start()

    def read(self):
        while True:
            self.__event.wait(0.5)
            try:
                return self._pipe.popleft()
            except IndexError:
                self.__event.clear()
                continue

    def write(self, data):
        self._written = True
        self._pipe.append(data)
        self.__event.set()

    @property
    def text(self):
        self._block.wait()
        return self._text

    def run(self):
        self.time_up()
        try:
            self._text = self._voice_recognition(self, False, self._time)
        finally:
            self._block.set()

    def get_audio_data(self):
        frames = collections.deque()
        chunk = True
        while chunk:
            chunk = self.read()
            frames.append(chunk)
        return AudioData(frame_data=b''.join(frames), sample_rate=self.sample_rate, sample_width=self.sample_width)


class TimeFusion:
    def __init__(self):
        self._time = 0

    def __call__(self, *args, **kwargs):
        return self._time

    def up(self):
        self._time = time.time()
