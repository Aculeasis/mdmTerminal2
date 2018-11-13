
from .proxy import monkey_patching_enable, monkey_patching_disable
import speech_recognition

Microphone = speech_recognition.Microphone
AudioData = speech_recognition.AudioData
UnknownValueError = speech_recognition.UnknownValueError
RequestError = speech_recognition.RequestError
WaitTimeoutError = speech_recognition.WaitTimeoutError


class Recognizer(speech_recognition.Recognizer):
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
