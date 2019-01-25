import audioop
import collections
import os
import threading
import time
from functools import lru_cache

from speech_recognition import Microphone, AudioData

from lib import snowboydetect
from utils import singleton, is_int

try:
    from webrtc_audio_processing import AudioProcessingModule
    APM_ERR = None
except ImportError as e:
    APM_ERR = 'Error importing webrtc_audio_processing: {}'.format(e)

try:
    from webrtcvad import Vad
except ImportError as e:
    Vad = None
    print('Error importing webrtcvad: {}'.format(e))


@singleton
class APMSettings:
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
        return not APM_ERR and self._cfg['enable']

    @property
    def conservative(self):
        return self._cfg['conservative']

    @property
    def failed(self):
        if self._cfg['enable'] and APM_ERR:
            return APM_ERR
        return None

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
        ap = AudioProcessingModule(aec_type=kwargs['aec_type'], enable_ns=True, agc_type=kwargs['agc_type'])
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


class Detector:
    def __init__(self, duration, width, rate, resample_rate):
        self._resample_rate = resample_rate
        self._rate = rate
        self._width = width
        self._sample_size = int(width * (self._resample_rate * duration / 1000))
        self._resample_state = None
        self._buffer = b''
        self._state = False
        if self._rate == self._resample_rate:
            self._resampler = lambda x: x
        else:
            self._resampler = self._audio_resampler

    def is_speech(self, data: bytes) -> bool:
        self._call_detector(self._resampler(data))
        return self._state

    def dynamic_energy(self):
        pass

    def _detector(self, chunk: bytes):
        pass

    def _call_detector(self, data: bytes):
        self._buffer += data
        buff_len = len(self._buffer)
        read_len = (buff_len // self._sample_size) * self._sample_size
        if read_len:
            for step in range(0, read_len, self._sample_size):
                self._detector(self._buffer[step: step + self._sample_size])
            self._buffer = self._buffer[read_len:]

    def _audio_resampler(self, buffer: bytes) -> bytes:
        buffer, self._resample_state = audioop.ratecv(
            buffer, self._width, 1, self._rate, self._resample_rate, self._resample_state
        )
        return buffer


class SnowboyDetector(Detector):
    def __init__(self, resource_path, snowboy_hot_word_files, sensitivity, audio_gain, width, rate, another, **_):
        self._snowboy = SnowboyDetector._constructor(resource_path, sensitivity, audio_gain, *snowboy_hot_word_files)
        super().__init__(150, width, rate, self._snowboy.SampleRate())
        self._another = another
        self._current_state = -2

    def detect(self, buffer: bytes) -> int:
        return self._detector(buffer)

    def is_speech(self, buffer: bytes) -> bool:
        return self._detector(buffer, True) >= 0

    def dynamic_energy(self):
        if self._another:
            self._another.dynamic_energy()

    def _detector(self, buffer: bytes, only_detect=False) -> int:
        self._buffer += self._resampler(buffer)
        if len(self._buffer) >= self._sample_size:
            if self._another:
                is_speech = self._another.is_speech(self._buffer)
                if only_detect:
                    self._current_state = 0 if is_speech else -2
                else:
                    self._current_state = self._snowboy.RunDetection(self._buffer)
            else:
                self._current_state = self._snowboy.RunDetection(self._buffer)
            self._buffer = b''
        return self._current_state

    @classmethod
    @lru_cache(maxsize=1)
    def _constructor(cls, resource_path, sensitivity, audio_gain, *snowboy_hot_word_files):
        sn = snowboydetect.SnowboyDetect(
            resource_filename=os.path.join(resource_path, 'resources', 'common.res').encode(),
            model_str=",".join(snowboy_hot_word_files).encode()
        )
        sn.SetAudioGain(audio_gain)
        sn.SetSensitivity(','.join([str(sensitivity)] * len(snowboy_hot_word_files)).encode())
        return sn


class DetectorVAD(Detector):
    def __init__(self, width, rate, lvl, **_):
        super().__init__(30, width, rate, 16000)
        self._vad = DetectorVAD._constructor(lvl)

    def _detector(self, chunk: bytes):
        self._state = self._vad.is_speech(chunk, self._resample_rate)

    @classmethod
    @lru_cache(maxsize=1)
    def _constructor(cls, lvl):
        return Vad(lvl)


class DetectorAPM(Detector):
    def __init__(self, width, rate, lvl, **_):
        super().__init__(10, width, rate, 16000)
        self._apm = DetectorAPM._constructor(lvl)

    def is_speech(self, data: bytes) -> bool:
        self._call_detector(self._resampler(data))
        self._state = self._apm.has_voice()
        return self._state

    def _detector(self, chunk: bytes):
        self._apm.process_stream(chunk)

    @classmethod
    @lru_cache(maxsize=1)
    def _constructor(cls, lvl):
        apm = AudioProcessingModule(enable_vad=True)
        apm.set_vad_level(lvl)
        return apm


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
            self._text = self._voice_recognition(self, True, self._time)
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
