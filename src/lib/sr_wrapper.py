
import audioop
import collections
import math
import os
import time

import speech_recognition

from lib import snowboydetect
from .proxy import proxies

Microphone = speech_recognition.Microphone
AudioData = speech_recognition.AudioData
AudioSource = speech_recognition.AudioSource
UnknownValueError = speech_recognition.UnknownValueError
RequestError = speech_recognition.RequestError
WaitTimeoutError = speech_recognition.WaitTimeoutError


class Interrupted(Exception):
    pass


class Recognizer(speech_recognition.Recognizer):
    def __init__(self, interrupt_check=None, sensitivity=0.45, hotword_callback=None, audio_gain=1.0):
        super().__init__()
        self._snowboy_result = 0
        self._interrupt_check = interrupt_check
        self._sensitivity = sensitivity
        self._hotword_callback = hotword_callback
        self._audio_gain = audio_gain
        self._no_energy_threshold = False

        self._noising = None

    def no_energy_threshold(self):
        self._no_energy_threshold = True

    def adaptive_noising(self, noising):
        self._noising = noising

    def calc_noise(self, buffer, sample_width, seconds_per_buffer):
        energy = audioop.rms(buffer, sample_width)  # energy of the audio signal

        # dynamically adjust the energy threshold using asymmetric weighted average
        damping = self.dynamic_energy_adjustment_damping ** seconds_per_buffer  # account for different chunk sizes and rates
        target_energy = energy * self.dynamic_energy_ratio
        self.energy_threshold = self.energy_threshold * damping + target_energy * (1 - damping)

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
        proxies.monkey_patching_enable('stt_google')
        try:
            return super().recognize_google(audio_data, key, language, show_all)
        finally:
            proxies.monkey_patching_disable()

    def recognize_wit(self, audio_data, key, show_all=False):
        proxies.monkey_patching_enable('stt_wit.ai')
        try:
            return super().recognize_wit(audio_data, key, show_all)
        finally:
            proxies.monkey_patching_disable()

    def recognize_bing(self, audio_data, key, language="en-US", show_all=False):
        proxies.monkey_patching_enable('stt_microsoft')
        try:
            return super().recognize_bing(audio_data, key, language, show_all)
        finally:
            proxies.monkey_patching_disable()

    def _get_detector(self, snowboy_location, snowboy_hot_word_files):
        detector = snowboydetect.SnowboyDetect(
            resource_filename=os.path.join(snowboy_location, "resources", "common.res").encode(),
            model_str=",".join(snowboy_hot_word_files).encode()
        )
        detector.SetAudioGain(self._audio_gain)
        detector.SetSensitivity(",".join([str(self._sensitivity)] * len(snowboy_hot_word_files)).encode())
        return detector

    # part of https://github.com/Uberi/speech_recognition/blob/master/speech_recognition/__init__.py#L574
    def snowboy_wait_for_hot_word(self, snowboy_location, snowboy_hot_word_files, source, timeout=None):
        self._snowboy_result = 0

        detector = self._get_detector(snowboy_location, snowboy_hot_word_files)
        snowboy_sample_rate = detector.SampleRate()

        elapsed_time = 0
        seconds_per_buffer = float(source.CHUNK) / source.SAMPLE_RATE
        resampling_state = None

        # buffers capable of holding 5 seconds of original and resampled audio
        five_seconds_buffer_count = int(math.ceil(5 / seconds_per_buffer))
        frames = collections.deque(maxlen=five_seconds_buffer_count)
        start_time = time.time()
        snowboy_result = 0
        while True:
            elapsed_time += seconds_per_buffer

            buffer = source.stream.read(source.CHUNK)
            if not buffer:
                break  # reached end of the stream
            frames.append(buffer)
            # resample audio to the required sample rate
            resampled_buffer, resampling_state = audioop.ratecv(buffer, source.SAMPLE_WIDTH, 1, source.SAMPLE_RATE,
                                                                snowboy_sample_rate, resampling_state)
            # run Snowboy on the resampled audio
            snowboy_result = detector.RunDetection(resampled_buffer)
            if snowboy_result > 0:
                # wake word found
                break
            elif snowboy_result == -1:
                raise RuntimeError("Error initializing streams or reading audio data")

            if time.time() - start_time > 0.05:
                if self._interrupt_check and self._interrupt_check():
                    raise Interrupted('Interrupted')
                if elapsed_time > 60:
                    raise Interrupted("listening timed out while waiting for hotword to be said")
                start_time = time.time()

            if self._noising and not self._noising():
                self.calc_noise(buffer, source.SAMPLE_WIDTH, seconds_per_buffer)

        self._snowboy_result = snowboy_result
        if self._hotword_callback:
            self._hotword_callback()
        return b"".join(frames), elapsed_time if elapsed_time < 5 else 5.0

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
        def speech_detect(resampling_state):
            # return True if snowboy detect speech
            resampled_buffer, resampling_state = audioop.ratecv(buffer, source.SAMPLE_WIDTH, 1,
                                                                source.SAMPLE_RATE,
                                                                snowboy_sample_rate, resampling_state)
            return detector.RunDetection(resampled_buffer) >= 0, resampling_state

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
        resampling_state = None
        if self._no_energy_threshold and snowboy_configuration:
            # Use snowboy to words detecting instead of energy_threshold
            detector = detector = self._get_detector(*snowboy_configuration)
            snowboy_sample_rate = detector.SampleRate()
        else:
            detector, snowboy_sample_rate = None, None

        while True:
            frames = collections.deque()

            if snowboy_configuration is None:
                # store audio input until the phrase starts
                while True:
                    # handle waiting too long for phrase by raising an exception
                    elapsed_time += seconds_per_buffer
                    if timeout and elapsed_time > timeout:
                        raise WaitTimeoutError("listening timed out while waiting for phrase to start")

                    buffer = source.stream.read(source.CHUNK)
                    if len(buffer) == 0: break  # reached end of the stream
                    frames.append(buffer)
                    if len(frames) > non_speaking_buffer_count:  # ensure we only keep the needed amount of non-speaking buffers
                        frames.popleft()

                    # detect whether speaking has started on audio input
                    if detector is None:
                        energy = audioop.rms(buffer, source.SAMPLE_WIDTH)  # energy of the audio signal
                        speech = energy > self.energy_threshold
                    else:
                        speech, resampling_state = speech_detect(resampling_state)
                    if speech:
                        break

                    # dynamically adjust the energy threshold using asymmetric weighted average
                    if self.dynamic_energy_threshold and detector is None:
                        damping = self.dynamic_energy_adjustment_damping ** seconds_per_buffer  # account for different chunk sizes and rates
                        target_energy = energy * self.dynamic_energy_ratio
                        self.energy_threshold = self.energy_threshold * damping + target_energy * (1 - damping)
            else:
                # read audio input until the hotword is said
                snowboy_location, snowboy_hot_word_files = snowboy_configuration
                buffer, delta_time = self.snowboy_wait_for_hot_word(snowboy_location, snowboy_hot_word_files, source, timeout)
                # Иначе он залипает на распознавании ключевых слов
                snowboy_configuration = None
                elapsed_time += delta_time
                if len(buffer) == 0: break  # reached end of the stream
                frames.append(buffer)

            # read audio input until the phrase ends
            pause_count, phrase_count = 0, 0
            phrase_start_time = elapsed_time
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
                if detector is None:
                    energy = audioop.rms(buffer, source.SAMPLE_WIDTH)  # unit energy of the audio signal within the buffer
                    speech = energy > self.energy_threshold
                else:
                    speech, resampling_state= speech_detect(resampling_state)
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

        return AudioData(frame_data, source.SAMPLE_RATE, source.SAMPLE_WIDTH)
