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
            if key in ('enable', 'conservative') and isinstance(val, bool):
                self._cfg[key] = val
            elif key == 'ns_lvl':
                val = self._to_int(val)
                if val is not None:
                    self._cfg[key] = min(3, max(0, val))
            elif key == 'agc_lvl':
                val = self._to_int(val)
                if val is not None:
                    self._cfg[key] = min(100, max(0, val))
            elif key == 'agc_target':
                val = self._to_int(val)
                if val is not None:
                    val = val * -1 if val < 0 else val
                    self._cfg[key] = min(31, max(0, val))
            elif key in ('aec_lvl', 'agc_type', 'aec_type'):
                val = self._to_int(val)
                if val is not None:
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


class SnowboyDetector:
    def __init__(self, resource_path, snowboy_hot_word_files, sensitivity, audio_gain, width, rate, webrtcvad):
        webrtcvad = min(4, max(0, webrtcvad))
        webrtcvad = webrtcvad if Vad else 0
        self._detector = _snowboy_constructor(resource_path, sensitivity, audio_gain, *snowboy_hot_word_files)

        self._resample_rate = self._detector.SampleRate()
        if webrtcvad and self._resample_rate not in (16000, 32000, 48000):
            self._resample_rate = 16000
        self._rate = rate
        self._width = width
        self._resample_state = None
        self._buffer = b''
        # sample duration in ms
        duration = 150
        if webrtcvad and duration not in (10, 20, 30):
            duration = 30
        self._sample_size = int(width * (self._resample_rate * duration / 1000))
        self._current_state = -2
        self._vad = _webrtcvad_constructor(webrtcvad)
        if self._rate == self._resample_rate:
            self._resampler = lambda x: x
        else:
            self._resampler = self.__resampler

    def detect(self, buffer: bytes) -> int:
        return self._detect(buffer)

    def is_speech(self, buffer: bytes) -> bool:
        return self._detect(buffer, True) >= 0

    def _detect(self, buffer: bytes, only_detect=False) -> int:
        self._buffer += self._resampler(buffer)
        if len(self._buffer) >= self._sample_size:
            if self._vad:
                current_state = self._current_state
                while len(self._buffer) >= self._sample_size:
                    vad_buffer, self._buffer = self._buffer[:self._sample_size], self._buffer[self._sample_size:]
                    if not self._vad.is_speech(vad_buffer, self._resample_rate):
                        current_state = -2
                    elif not only_detect:
                        current_state = self._detector.RunDetection(vad_buffer)
                    else:
                        current_state = 0
                    if current_state != self._current_state:
                        break
                self._current_state = current_state
            else:
                self._current_state = self._detector.RunDetection(self._buffer)
                self._buffer = b''
        return self._current_state

    def __resampler(self, buffer: bytes) -> bytes:
        buffer, self._resample_state = audioop.ratecv(
            buffer, self._width, 1, self._rate, self._resample_rate, self._resample_state
        )
        return buffer


class StreamRecognition(threading.Thread):
    def __init__(self, voice_recognition):
        super().__init__()
        self._time = TimeFusion()
        self._voice_recognition = voice_recognition
        self._pipe = None
        self.sample_rate = None
        self.sample_width = None
        self.work = True
        self._text = ''
        self._written = False
        self._block = threading.Event()
        self.__event = threading.Event()

    @property
    def ready(self):
        return self._pipe is not None

    @property
    def is_ok(self):
        return self._written and self.ready

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


@lru_cache(maxsize=1)
def _webrtcvad_constructor(webrtcvad):
    return Vad(webrtcvad - 1) if webrtcvad else None


@lru_cache(maxsize=1)
def _snowboy_constructor(resource_path, sensitivity, audio_gain, *snowboy_hot_word_files):
    sn = snowboydetect.SnowboyDetect(
        resource_filename=os.path.join(resource_path, 'resources', 'common.res').encode(),
        model_str=",".join(snowboy_hot_word_files).encode()
    )
    sn.SetAudioGain(audio_gain)
    sn.SetSensitivity(','.join([str(sensitivity)] * len(snowboy_hot_word_files)).encode())
    return sn
