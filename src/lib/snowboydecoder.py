#!/usr/bin/env python

import audioop
import collections
import os
import sys
import time

import pyaudio

from lib import snowboydetect
from lib.sr_wrapper import Microphone

TOP_DIR = os.path.abspath(sys.path[0])
RESOURCE_FILE = os.path.join(os.path.join(TOP_DIR, "resources"), "common.res")


class RingBuffer:
    """Ring buffer to hold audio from PortAudio"""
    def __init__(self, size, rate, width, nchannels, resample_rate):
        seconds_per_buffer = float(size) / rate
        five_seconds_buffer_count = int(5 / seconds_per_buffer)
        self._buffer = collections.deque(maxlen=five_seconds_buffer_count)
        self._rate = rate
        self._resample_rate = resample_rate
        self._width = width
        self._nchannels = nchannels
        self._resample_state = None
        if self._rate == self._resample_rate:
            self.extend = self._extend
        else:
            self.extend = self._resample

    def _extend(self, data):
        """Adds data to the end of buffer"""
        self._buffer.append(data)

    def _resample(self, data):
        data, self._resample_state = audioop.ratecv(
            data, self._width, self._nchannels, self._rate, self._resample_rate, self._resample_state
        )
        self._buffer.append(data)

    def get(self):
        """Retrieves data from the beginning of buffer and clears it"""
        try:
            return b''.join(self._buffer)
        finally:
            self._buffer.clear()

    def audio_callback(self, in_data, *_):
        self.extend(in_data)
        return None, pyaudio.paContinue


class HotwordDetector(object):
    """
    Snowboy decoder to detect whether a keyword specified by `decoder_model`
    exists in a microphone input stream.

    :param decoder_model: decoder model file path, a string or a list of strings
    :param resource: resource file path.
    :param sensitivity: decoder sensitivity, a float of a list of floats.
                              The bigger the value, the more senstive the
                              decoder. If an empty list is provided, then the
                              default sensitivity in the model will be used.
    :param audio_gain: multiply input volume by this factor.
    """
    def __init__(self, decoder_model, resource=RESOURCE_FILE, sensitivity=None, audio_gain=1, device_index=None):
        self.audio = None
        self.stream_in = None
        self._device_index = device_index
        self._frames_per_buffer = 2048
        sensitivity = sensitivity or []
        if not isinstance(decoder_model, list):
            decoder_model = [decoder_model]
        if not isinstance(sensitivity, list):
            sensitivity = [sensitivity]
        model_str = ",".join(decoder_model)

        self.detector = snowboydetect.SnowboyDetect(
            resource_filename=resource.encode(), model_str=model_str.encode())
        self.detector.SetAudioGain(audio_gain)
        self.num_hotwords = self.detector.NumHotwords()

        if self.num_hotwords > 1 and len(sensitivity) == 1:
            sensitivity = sensitivity*self.num_hotwords
        if len(sensitivity) != 0:
            assert self.num_hotwords == len(sensitivity), \
                "number of hotwords in decoder_model (%d) and sensitivity " \
                "(%d) does not match" % (self.num_hotwords, len(sensitivity))
        sensitivity_str = ",".join([str(t) for t in sensitivity])
        if len(sensitivity) != 0:
            self.detector.SetSensitivity(sensitivity_str.encode())

        self._resample_rate = self.detector.SampleRate()
        self._rate = Microphone.DEFAULT_RATE or self._resample_rate
        self._width = int(self.detector.BitsPerSample() / 8)
        self._nchannels = self.detector.NumChannels()

        self.ring_buffer = RingBuffer(
            self._frames_per_buffer, self._rate, self._width, self._nchannels, self._resample_rate)
        self._terminate = False

    def start(self, detected_callback, interrupt_check, sleep_time=0.03):
        """
        Start the voice detector. For every `sleep_time` second it checks the
        audio buffer for triggering keywords. If detected, then call
        corresponding function in `detected_callback`, which can be a single
        function (single model) or a list of callback functions (multiple
        models). Every loop it also calls `interrupt_check` -- if it returns
        True, then breaks from the loop and return.
    
        :param detected_callback: a function or list of functions. The number of
                                  items must match the number of models in
                                  `decoder_model`.
        :param interrupt_check: a function that returns True if the main loop
                                needs to stop.
        :param float sleep_time: how much time in second every loop waits.
        :return: None
        """
        self._terminate = False
        self.audio = pyaudio.PyAudio()
        self.stream_in = self.audio.open(
            input_device_index=self._device_index,
            input=True, output=False,
            format=self.audio.get_format_from_width(self._width),
            channels=self._nchannels,
            rate=self._rate,
            frames_per_buffer=self._frames_per_buffer,
            stream_callback=self.ring_buffer.audio_callback)
    
        if not isinstance(detected_callback, list):
            detected_callback = [detected_callback]
        if len(detected_callback) == 1 and self.num_hotwords > 1:
            detected_callback *= self.num_hotwords

        assert self.num_hotwords == len(detected_callback), \
            "Error: hotwords in your models (%d) do not match the number of " \
            "callbacks (%d)" % (self.num_hotwords, len(detected_callback))

        while not (self._terminate or interrupt_check()):
            data = self.ring_buffer.get()
            if not data:
                time.sleep(sleep_time)
                continue

            ans = self.detector.RunDetection(data)
            if ans == -1:
                print("Error initializing streams or reading audio data")
            elif ans > 0:
                callback = detected_callback[ans-1]
                if callback is not None:
                    callback(ans)

    def terminate(self):
        """
        Terminate audio stream and start() loop. Users cannot call start() again to detect.
        :return: None
        """
        self.stream_in.stop_stream()
        self.stream_in.close()
        self.audio.terminate()
        self._terminate = True
