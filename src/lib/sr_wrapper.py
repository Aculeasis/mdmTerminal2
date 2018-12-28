# https://github.com/Uberi/speech_recognition
# Copyright (c) 2014-2017, Anthony Zhang <azhang9@gmail.com>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the
# following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions
# and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions
# and the following disclaimer in the documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse
# or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# This code was modified by Aculeasis, 2018

import audioop
import collections
import json
import math
import os
import threading
import time
from functools import lru_cache

import speech_recognition

try:
    from webrtc_audio_processing import AudioProcessingModule
    APM_ERR = None
except (ModuleNotFoundError, ImportError) as e:
    APM_ERR = 'Error importing webrtc_audio_processing: {}'.format(e)

try:
    from webrtcvad import Vad
    WEBRTCVAD = True
except (ModuleNotFoundError, ImportError) as e:
    WEBRTCVAD = False
    print('Error importing webrtcvad: {}'.format(e))
from lib import snowboydetect
from .proxy import proxies
from utils import singleton, is_int

AudioData = speech_recognition.AudioData
AudioSource = speech_recognition.AudioSource
UnknownValueError = speech_recognition.UnknownValueError
RequestError = speech_recognition.RequestError
WaitTimeoutError = speech_recognition.WaitTimeoutError
get_flac_converter = speech_recognition.get_flac_converter


@singleton
class APMSettings:
    def __init__(self):
        self._cfg = {
            'enable': False,
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
            if key == 'enable' and isinstance(val, bool):
                self._cfg['enable'] = val
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

    @lru_cache()
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


class Interrupted(Exception):
    pass


class Microphone(speech_recognition.Microphone):
    def __init__(self, device_index=None, _=None, chunk_size=1024):
        super().__init__(device_index, 16000, chunk_size)

    def __enter__(self):
        assert self.stream is None, "This audio source is already inside a context manager"
        self.audio = self.pyaudio_module.PyAudio()
        try:
            self.stream = Microphone.get_microphone_stream(
                self.audio.open(
                    input_device_index=self.device_index, channels=1,
                    format=self.format, rate=self.SAMPLE_RATE, frames_per_buffer=self.CHUNK,
                    input=True,  # stream is an input stream
                ), self.SAMPLE_WIDTH, self.SAMPLE_RATE
            )
        except Exception:
            self.audio.terminate()
            raise
        return self

    @classmethod
    def get_microphone_stream(cls, pyaudio_stream, width, rate):
        if APMSettings().enable:
            return Microphone.MicrophoneStreamAPM(pyaudio_stream, width, rate)
        else:
            return speech_recognition.Microphone.MicrophoneStream(pyaudio_stream)

    class MicrophoneStreamAPM(speech_recognition.Microphone.MicrophoneStream):
        def __init__(self, pyaudio_stream, width, rate):
            super().__init__(pyaudio_stream)
            self._ap = APMSettings().instance
            self._ap.set_stream_format(rate, 1)
            self._buffer = b''
            self._sample_size = width * int(rate * 10 / 1000)

        def read(self, size):
            return b''.join(chunk for chunk in self._reader(super().read(size)))

        def _reader(self, data: bytes):
            self._buffer += data
            buff_len = len(self._buffer)
            read_len = (buff_len // self._sample_size) * self._sample_size
            if read_len:
                for step in range(0, read_len, self._sample_size):
                    yield self._ap.process_stream(self._buffer[step: step + self._sample_size])
                self._buffer = self._buffer[read_len:]


class SnowboyDetector:
    def __init__(self, resource_path, snowboy_hot_word_files, sensitivity, audio_gain, width, rate, webrtcvad):
        webrtcvad = min(4, max(0, webrtcvad))
        webrtcvad = webrtcvad if WEBRTCVAD else 0
        self._detector = snowboydetect.SnowboyDetect(
            resource_filename=os.path.join(resource_path, 'resources', 'common.res').encode(),
            model_str=",".join(snowboy_hot_word_files).encode()
        )
        self._detector.SetAudioGain(audio_gain)
        self._detector.SetSensitivity(','.join([str(sensitivity)] * len(snowboy_hot_word_files)).encode())

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
        self._vad = Vad(webrtcvad - 1) if webrtcvad else None
        if self._rate == 16000:
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
                while len(self._buffer) >= self._sample_size:
                    vad_buffer, self._buffer = self._buffer[:self._sample_size], self._buffer[self._sample_size:]
                    if not self._vad.is_speech(vad_buffer, self._resample_rate):
                        self._current_state = -2
                    elif not only_detect:
                        self._current_state = self._detector.RunDetection(vad_buffer)
                    else:
                        self._current_state = 0
            else:
                self._current_state = self._detector.RunDetection(self._buffer)
                self._buffer = b''
        return self._current_state

    def __resampler(self, buffer: bytes) -> bytes:
        buffer, self._resample_state = audioop.ratecv(
            buffer, self._width, 1, self._rate, self._resample_rate, self._resample_state
        )
        return buffer


class Recognizer(speech_recognition.Recognizer):
    def __init__(self,
                 sensitivity=0.45, audio_gain=1.0,
                 hotword_callback=None, interrupt_check=None, record_callback=None, noising=None, silent_multiplier=1.0
                 ):
        super().__init__()
        self._snowboy_result = 0
        self._interrupt_check = interrupt_check
        self._sensitivity = sensitivity
        self._hotword_callback = hotword_callback
        self._audio_gain = audio_gain
        self._no_energy_threshold = False
        self._webrtcvad = 0

        self._noising = noising
        self._record_callback = record_callback

        silent_multiplier = min(5.0, max(0.1, silent_multiplier))
        self.pause_threshold *= silent_multiplier
        self.non_speaking_duration *= silent_multiplier

    def no_energy_threshold(self):
        self._no_energy_threshold = True

    def use_webrtcvad(self, webrtcvad):
        self._webrtcvad = webrtcvad

    def _calc_noise(self, buffer, sample_width, seconds_per_buffer):
        energy = audioop.rms(buffer, sample_width)  # energy of the audio signal

        # dynamically adjust the energy threshold using asymmetric weighted average
        damping = self.dynamic_energy_adjustment_damping ** seconds_per_buffer  # account for different chunk sizes and rates
        target_energy = energy * self.dynamic_energy_ratio
        self.energy_threshold = self.energy_threshold * damping + target_energy * (1 - damping)

    def _get_detector(self, source, snowboy_configuration):
        if not snowboy_configuration:
            return None
        snowboy_location, snowboy_hot_word_files = snowboy_configuration
        return SnowboyDetector(
                snowboy_location, snowboy_hot_word_files, self._sensitivity, self._audio_gain,
                source.SAMPLE_WIDTH, source.SAMPLE_RATE, self._webrtcvad
            )

    @property
    def get_model(self):
        return self._snowboy_result

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def recognize_bing(self, audio_data, key, language="en-US", show_all=False):
        proxies.monkey_patching_enable('stt_microsoft')
        try:
            return super().recognize_bing(audio_data, key, language, show_all)
        finally:
            proxies.monkey_patching_disable()

    # part of https://github.com/Uberi/speech_recognition/blob/master/speech_recognition/__init__.py#L574
    # noinspection PyMethodOverriding
    def snowboy_wait_for_hot_word(self, snowboy, source, timeout=None):
        self._snowboy_result = 0

        elapsed_time = 0
        seconds_per_buffer = float(source.CHUNK) / source.SAMPLE_RATE
        # buffers capable of holding 5 seconds of original and resampled audio
        five_seconds_buffer_count = int(math.ceil(5 / seconds_per_buffer))
        frames = collections.deque(maxlen=five_seconds_buffer_count)
        start_time = time.time() + 0.2
        snowboy_result = 0
        while True:
            elapsed_time += seconds_per_buffer

            buffer = source.stream.read(source.CHUNK)
            if not buffer:
                break  # reached end of the stream
            frames.append(buffer)
            snowboy_result = snowboy.detect(buffer)
            if snowboy_result > 0:
                # wake word found
                break
            elif snowboy_result == -1:
                raise RuntimeError("Error initializing streams or reading audio data")

            if time.time() > start_time:
                if self._interrupt_check and self._interrupt_check():
                    raise Interrupted('Interrupted')
                if elapsed_time > 180:
                    raise Interrupted("listening timed out while waiting for hotword to be said")
                start_time = time.time() + 0.2

            if self._noising and not self._noising():
                self._calc_noise(buffer, source.SAMPLE_WIDTH, seconds_per_buffer)

        self._snowboy_result = snowboy_result
        if self._hotword_callback:
            self._hotword_callback()
        return frames, elapsed_time if elapsed_time < 5 else 5.0

    # part of https://github.com/Uberi/speech_recognition/blob/master/speech_recognition/__init__.py#L616
    def listen(self, source, timeout=None, phrase_time_limit=None, snowboy_configuration=None):
        """
        Records a single phrase from ``source`` (an ``AudioSource`` instance) into an ``AudioData`` instance, which it returns.

        This is done by waiting until the audio has an energy above ``recognizer_instance.energy_threshold`` (the user has started speaking), and then recording until it encounters ``recognizer_instance.pause_threshold`` seconds of non-speaking or there is no more audio input. The ending silence is not included.

        The ``timeout`` parameter is the maximum number of seconds that this will wait for a phrase to start before giving up and throwing an ``speech_recognition.WaitTimeoutError`` exception. If ``timeout`` is ``None``, there will be no wait timeout.

        The ``phrase_time_limit`` parameter is the maximum number of seconds that this will allow a phrase to continue before stopping and returning the part of the phrase processed before the time limit was reached. The resulting audio will be the phrase cut off at the time limit. If ``phrase_timeout`` is ``None``, there will be no phrase time limit.

        The ``snowboy_configuration`` parameter allows integration with `Snowboy <https://snowboy.kitt.ai/>`__, an offline, high-accuracy, power-efficient hotword recognition engine. When used, this function will pause until Snowboy detects a hotword, after which it will unpause. This parameter should either be ``None`` to turn off Snowboy support, or a tuple of the form ``(SNOWBOY_LOCATION, LIST_OF_HOT_WORD_FILES)``, where ``SNOWBOY_LOCATION`` is the path to the Snowboy root directory, and ``LIST_OF_HOT_WORD_FILES`` is a list of paths to Snowboy hotword configuration files (`*.pmdl` or `*.umdl` format).

        This operation will always complete within ``timeout + phrase_timeout`` seconds if both are numbers, either by returning the audio data, or by raising a ``speech_recognition.WaitTimeoutError`` exception.
        """
        assert isinstance(source, AudioSource), "Source must be an audio source"
        assert source.stream is not None, "Audio source must be entered before listening, see documentation for ``AudioSource``; are you using ``source`` outside of a ``with`` statement?"
        assert self.pause_threshold >= self.non_speaking_duration >= 0

        seconds_per_buffer = float(source.CHUNK) / source.SAMPLE_RATE
        pause_buffer_count = int(math.ceil(self.pause_threshold / seconds_per_buffer))  # number of buffers of non-speaking audio during a phrase, before the phrase should be considered complete
        phrase_buffer_count = int(math.ceil(self.phrase_threshold / seconds_per_buffer))  # minimum number of buffers of speaking audio before we consider the speaking audio a phrase
        non_speaking_buffer_count = int(math.ceil(self.non_speaking_duration / seconds_per_buffer))  # maximum number of buffers of non-speaking audio to retain before and after a phrase

        # read audio input for phrases until there is a phrase that is long enough
        elapsed_time = 0  # number of seconds of audio read
        buffer = b""  # an empty buffer means that the stream has ended and there is no data left to read
        energy = 0
        detector = self._get_detector(source, snowboy_configuration)
        send_record_starting = False
        # Use snowboy to words detecting instead of energy_threshold
        use_detector = detector and self._no_energy_threshold
        while True:
            frames = collections.deque()

            if snowboy_configuration is None:
                # store audio input until the phrase starts
                while True:
                    # handle waiting too long for phrase by raising an exception
                    elapsed_time += seconds_per_buffer
                    if timeout and elapsed_time > timeout:
                        if self._record_callback and send_record_starting:
                            self._record_callback(False)
                        raise WaitTimeoutError("listening timed out while waiting for phrase to start")

                    buffer = source.stream.read(source.CHUNK)
                    if len(buffer) == 0: break  # reached end of the stream
                    frames.append(buffer)
                    if len(frames) > non_speaking_buffer_count:  # ensure we only keep the needed amount of non-speaking buffers
                        frames.popleft()

                    # detect whether speaking has started on audio input
                    if use_detector:
                        speech = detector.is_speech(buffer)
                    else:
                        energy = audioop.rms(buffer, source.SAMPLE_WIDTH)  # energy of the audio signal
                        speech = energy > self.energy_threshold
                    if speech:
                        break

                    # dynamically adjust the energy threshold using asymmetric weighted average
                    if self.dynamic_energy_threshold and not use_detector:
                        damping = self.dynamic_energy_adjustment_damping ** seconds_per_buffer  # account for different chunk sizes and rates
                        target_energy = energy * self.dynamic_energy_ratio
                        self.energy_threshold = self.energy_threshold * damping + target_energy * (1 - damping)
            else:
                # read audio input until the hotword is said
                buffer, delta_time = self.snowboy_wait_for_hot_word(detector, source)
                # Иначе он залипает на распознавании ключевых слов
                snowboy_configuration = None
                elapsed_time += delta_time
                if len(buffer) == 0: break  # reached end of the stream
                frames.append(b''.join(buffer))

            # read audio input until the phrase ends
            pause_count, phrase_count = 0, 0
            phrase_start_time = elapsed_time
            if self._record_callback and not send_record_starting:
                send_record_starting = True
                self._record_callback(True)
            while True:
                # handle phrase being too long by cutting off the audio
                elapsed_time += seconds_per_buffer
                if phrase_time_limit and elapsed_time - phrase_start_time > phrase_time_limit:
                    break

                buffer = source.stream.read(source.CHUNK)
                if len(buffer) == 0: break  # reached end of the stream
                frames.append(buffer)
                phrase_count += 1

                # check if speaking has stopped for longer than the pause threshold on the audio input
                if use_detector:
                    speech = detector.is_speech(buffer)
                else:
                    energy = audioop.rms(buffer, source.SAMPLE_WIDTH)  # unit energy of the audio signal within the buffer
                    speech = energy > self.energy_threshold
                if speech:
                    pause_count = 0
                else:
                    pause_count += 1
                if pause_count > pause_buffer_count:  # end of the phrase
                    break

            # check how long the detected phrase is, and retry listening if the phrase is too short
            phrase_count -= pause_count  # exclude the buffers for the pause before the phrase
            if phrase_count >= phrase_buffer_count or len(buffer) == 0: break  # phrase is long enough or we've reached the end of the stream, so stop listening

        # obtain frame data
        for i in range(pause_count - non_speaking_buffer_count): frames.pop()  # remove extra non-speaking frames at the end
        frame_data = b"".join(frames)
        if self._record_callback and send_record_starting:
            self._record_callback(False)
        return AudioData(frame_data, source.SAMPLE_RATE, source.SAMPLE_WIDTH)

    def listen2(self, source, timeout, phrase_time_limit, snowboy_configuration, recognition):
        assert isinstance(source, AudioSource), "Source must be an audio source"
        assert source.stream is not None, "Audio source must be entered before listening, see documentation for ``AudioSource``; are you using ``source`` outside of a ``with`` statement?"
        assert self.pause_threshold >= self.non_speaking_duration >= 0

        seconds_per_buffer = float(source.CHUNK) / source.SAMPLE_RATE
        # number of buffers of non-speaking audio during a phrase, before the phrase should be considered complete
        pause_buffer_count = int(math.ceil(self.pause_threshold / seconds_per_buffer))
        # minimum number of buffers of speaking audio before we consider the speaking audio a phrase
        phrase_buffer_count = int(math.ceil(self.phrase_threshold / seconds_per_buffer))

        # read audio input for phrases until there is a phrase that is long enough
        elapsed_time = 0  # number of seconds of audio read
        buffer = b""  # an empty buffer means that the stream has ended and there is no data left to read
        # Use snowboy to words detecting instead of energy_threshold
        detector = self._get_detector(source, snowboy_configuration)
        send_record_starting = False
        voice_recognition = StreamRecognition(recognition)
        while True:
            if snowboy_configuration is None:
                # store audio input until the phrase starts
                while True:
                    # handle waiting too long for phrase by raising an exception
                    elapsed_time += seconds_per_buffer
                    if timeout and elapsed_time > timeout:
                        if self._record_callback and send_record_starting:
                            self._record_callback(False)
                        voice_recognition.terminate()
                        raise WaitTimeoutError("listening timed out while waiting for phrase to start")

                    buffer = source.stream.read(source.CHUNK)
                    if len(buffer) == 0: break  # reached end of the stream
                    voice_recognition.write(buffer)

                    # detect whether speaking has started on audio input
                    if detector.is_speech(buffer):
                        break
            else:
                # read audio input until the hotword is said
                buffer, delta_time = self.snowboy_wait_for_hot_word(detector, source)
                # Иначе он залипает на распознавании ключевых слов
                snowboy_configuration = None
                voice_recognition.init(buffer, None, source.SAMPLE_RATE, source.SAMPLE_WIDTH)
                elapsed_time += delta_time
                if len(buffer) == 0:
                    break  # reached end of the stream

            # read audio input until the phrase ends
            pause_count, phrase_count = 0, 0
            phrase_start_time = elapsed_time
            if self._record_callback and not send_record_starting:
                send_record_starting = True
                self._record_callback(True)
            while True:
                # handle phrase being too long by cutting off the audio
                elapsed_time += seconds_per_buffer
                if phrase_time_limit and elapsed_time - phrase_start_time > phrase_time_limit:
                    break

                buffer = source.stream.read(source.CHUNK)
                if len(buffer) == 0:
                    break  # reached end of the stream
                voice_recognition.write(buffer)
                phrase_count += 1

                if detector.is_speech(buffer):
                    pause_count = 0
                else:
                    pause_count += 1
                if pause_count > pause_buffer_count:  # end of the phrase
                    break

            # check how long the detected phrase is, and retry listening if the phrase is too short
            phrase_count -= pause_count  # exclude the buffers for the pause before the phrase
            if phrase_count >= phrase_buffer_count or len(buffer) == 0:
                break  # phrase is long enough or we've reached the end of the stream, so stop listening

        if self._record_callback and send_record_starting:
            self._record_callback(False)

        voice_recognition.end()
        if voice_recognition.ready:
            if not voice_recognition.is_ok:
                voice_recognition.work = False
                raise Interrupted('None')
        else:
            voice_recognition.work = False
            raise Interrupted('None')
        return voice_recognition


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


def google_reply_parser(text: str) -> str:
    # ignore any blank blocks
    actual_result = None
    for line in text.split('\n'):
        if not line:
            continue
        try:
            result = json.loads(line).get('result', [])
        except json.JSONDecodeError:
            continue
        if result and isinstance(result[0], dict):
            actual_result = result[0].get('alternative')
            break

    # print(actual_result)
    if not actual_result:
        raise UnknownValueError()

    if 'confidence' in actual_result:
        # return alternative with highest confidence score
        return max(actual_result, key=lambda alternative: alternative['confidence']).get('transcript')
    else:
        # when there is no confidence available, we arbitrarily choose the first hypothesis.
        return actual_result[0].get('transcript')
