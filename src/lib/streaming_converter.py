import subprocess
import threading
import wave
from collections import deque
from io import BytesIO

from .sr_wrapper import AudioData, get_flac_converter

CMD = {
    'mp3': ['lame', '-htv', '--silent', '-', '-'],
    'opus': ['opusenc', '--quiet', '--discard-comments', '--ignorelength', '-', '-'],
    'flac': [get_flac_converter(), '--totally-silent', '--best', '--stdout', '--ignore-chunk-sizes', '-']
}


class AudioConverter(threading.Thread):
    IN_CHUNK_SIZE = 1024 * 8
    OUT_CHUNK_SIZE = 1024 * 4
    POPEN_TIMEOUT = 10
    JOIN_TIMEOUT = 10

    def __init__(self, adata: AudioData, ext, convert_rate=None, convert_width=None):
        super().__init__()

        self._adata = adata
        self._stream = _StreamPipe()
        self._wave, self._in_out, self._popen = None, None, None

        self._sample_rate = adata.sample_rate if convert_rate is None else convert_rate
        self._sample_width = adata.sample_width if convert_width is None else convert_width
        self._format = ext

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def read(self, *_):
        return self._stream.read()

    def run(self):
        with BytesIO(self._adata.get_raw_data(self._sample_rate, self._sample_width)) as fp:
            del self._adata
            self._start_processing()
            while True:
                chunk = fp.read(self.IN_CHUNK_SIZE)
                if not chunk:
                    break
                self._wave.writeframesraw(chunk)
        self._end_processing()

    def _start_processing(self):
        self._popen = subprocess.Popen(CMD[self._format], stdout=subprocess.PIPE, stdin=subprocess.PIPE)
        self._in_out = _InOut(self._popen.stdout, self._stream, self.OUT_CHUNK_SIZE)
        self._wave = _WaveWrite(self._popen.stdin)
        self._wave.setnchannels(1)
        self._wave.setsampwidth(self._sample_width)
        self._wave.setframerate(self._sample_rate)
        self._wave.write_header()

    def _end_processing(self):
        self._wave.close()
        self._popen.stdin.close()
        try:
            self._popen.wait(self.POPEN_TIMEOUT)
        except subprocess.TimeoutExpired:
            pass
        self._in_out.join(timeout=self.JOIN_TIMEOUT)
        self._popen.stdout.close()
        self._popen.kill()
        self._stream.write(b'')


class _WaveWrite(wave.Wave_write):
    def _ensure_header_written(self, _):
        pass

    def _patchheader(self):
        pass

    def write_header(self, init_length=0xFFFFFFF):  # Задаем 'бесконечную' длину файла
        self._write_header(init_length)


class _StreamPipe:
    def __init__(self):
        self._pipe = deque()
        self.__event = threading.Event()

    def read(self):
        while True:
            self.__event.wait(1)
            try:
                return self._pipe.popleft()
            except IndexError:
                self.__event.clear()
                continue

    def write(self, data):
        self._pipe.append(data)
        self.__event.set()

    def close(self):
        pass

    def flush(self):
        pass

    @staticmethod
    def tell():
        return 0


class _InOut(threading.Thread):
    def __init__(self, in_, out_, chunk_size):
        super().__init__()
        self._in = in_
        self._out = out_
        self._chunk_size = chunk_size
        self.start()

    def run(self):
        while True:
            try:
                chunk = self._in.read(self._chunk_size)
            except ValueError:
                break
            if not chunk:
                break
            self._out.write(chunk)