
import audioop
import collections
import math
import os
import sys
import time

import speech_recognition

from .proxy import monkey_patching_enable, monkey_patching_disable

Microphone = speech_recognition.Microphone
AudioData = speech_recognition.AudioData
UnknownValueError = speech_recognition.UnknownValueError
RequestError = speech_recognition.RequestError
WaitTimeoutError = speech_recognition.WaitTimeoutError


class Recognizer(speech_recognition.Recognizer):
    def __init__(self):
        super().__init__()
        self._snowboy_result = 0
        self._sensitivity = 0.45
        self._interrupt_check = None

    @property
    def get_model(self):
        return self._snowboy_result

    def set_sensitivity(self, sensitivity):
        self._sensitivity = sensitivity

    def set_interrupt(self, interrupt):
        self._interrupt_check = interrupt

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def recognize_google(self, audio_data, key=None, language="en-US", show_all=False):
        monkey_patching_enable('stt_google')
        try:
            return super().recognize_google(audio_data, key, language, show_all)
        finally:
            monkey_patching_disable()

    def recognize_wit(self, audio_data, key, show_all=False):
        monkey_patching_enable('stt_wit.ai')
        try:
            return super().recognize_wit(audio_data, key, show_all)
        finally:
            monkey_patching_disable()

    def recognize_bing(self, audio_data, key, language="en-US", show_all=False):
        monkey_patching_enable('stt_microsoft')
        try:
            return super().recognize_bing(audio_data, key, language, show_all)
        finally:
            monkey_patching_disable()

    def snowboy_wait_for_hot_word(self, snowboy_location, snowboy_hot_word_files, source, timeout=None):
        # load snowboy library (NOT THREAD SAFE)
        sys.path.append(snowboy_location)
        import snowboydetect
        sys.path.pop()

        detector = snowboydetect.SnowboyDetect(
            resource_filename=os.path.join(snowboy_location, "resources", "common.res").encode(),
            model_str=",".join(snowboy_hot_word_files).encode()
        )
        detector.SetAudioGain(1.0)
        detector.SetSensitivity(",".join([str(self._sensitivity)] * len(snowboy_hot_word_files)).encode())
        snowboy_sample_rate = detector.SampleRate()

        elapsed_time = 0
        seconds_per_buffer = float(source.CHUNK) / source.SAMPLE_RATE
        resampling_state = None

        # buffers capable of holding 5 seconds of original and resampled audio
        five_seconds_buffer_count = int(math.ceil(5 / seconds_per_buffer))
        frames = collections.deque(maxlen=five_seconds_buffer_count)
        resampled_frames = collections.deque(maxlen=five_seconds_buffer_count)
        start_time = time.time()
        snowboy_result = 0
        while True:
            elapsed_time += seconds_per_buffer
            if timeout and elapsed_time > timeout:
                raise WaitTimeoutError("listening timed out while waiting for hotword to be said")

            buffer = source.stream.read(source.CHUNK)
            if len(buffer) == 0: break  # reached end of the stream
            frames.append(buffer)

            # resample audio to the required sample rate
            resampled_buffer, resampling_state = audioop.ratecv(buffer, source.SAMPLE_WIDTH, 1, source.SAMPLE_RATE,
                                                                snowboy_sample_rate, resampling_state)
            resampled_frames.append(resampled_buffer)

            # run Snowboy on the resampled audio
            snowboy_result = detector.RunDetection(b"".join(resampled_frames))
            assert snowboy_result != -1, "Error initializing streams or reading audio data"
            if snowboy_result > 0: break  # wake word found
            if self._interrupt_check and time.time() - start_time > 0.1:
                if self._interrupt_check():
                    raise WaitTimeoutError('Interrupted')
                time.sleep(0.01)
                start_time = time.time()
        self._snowboy_result = snowboy_result
        return b"".join(frames), elapsed_time
