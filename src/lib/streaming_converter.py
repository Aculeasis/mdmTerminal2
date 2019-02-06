import audioop
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

    def __init__(self, adata, ext, convert_rate=None, convert_width=None):
        super().__init__()

        self._adata = adata
        self._stream, self._wave = None, None

        self._sample_rate = adata.sample_rate if convert_rate is None else convert_rate
        self._sample_width = adata.sample_width if convert_width is None else convert_width
        self._format = ext
        self._work = True

    def __enter__(self):
        self._start_processing()
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._work = False

    def read(self, *_) -> bytes:
        return self._stream.read()

    def run(self):
        if isinstance(self._adata, AudioData):
            self._run_adata()
        else:
            self._run_deque()
        self._end_processing()

    def _run_deque(self):
        state = None
        while self._adata.work and self._work:
            chunk = self._adata.read()
            if not chunk:
                break
            if self._adata.sample_rate != self._sample_rate:
                chunk, state = audioop.ratecv(
                    chunk, self._sample_width, 1, self._adata.sample_rate, self._sample_rate, state
                )
            if not self._processing(chunk):
                break

    def _run_adata(self):
        with BytesIO(self._adata.get_raw_data(self._sample_rate, self._sample_width)) as fp:
            self._adata = None
            while self._work:
                chunk = fp.read(self.IN_CHUNK_SIZE)
                if not (chunk and self._processing(chunk)):
                    break

    def _processing(self, data: bytes):
        if self._wave:
            try:
                self._wave.writeframesraw(data)
            except BrokenPipeError:
                return False
        else:
            self._stream.write(data)
        return True

    def _start_processing(self):
        self._stream = self._get_stream()
        if self._format != 'pcm':
            self._wave = _WaveWrite(self._stream)
            self._wave.setnchannels(1)
            self._wave.setsampwidth(self._sample_width)
            self._wave.setframerate(self._sample_rate)
            self._wave.write_header()

    def _end_processing(self):
        if self._wave:
            self._wave.close()
        self._stream.end()

    def _get_stream(self):
        if self._format in CMD:
            return _StreamPopen(CMD[self._format])
        else:
            return _StreamPipe()


class _WaveWrite(wave.Wave_write):
    def _ensure_header_written(self, _):
        pass

    def _patchheader(self):
        pass

    def write_header(self, init_length=0xFFFFFFF):  # Задаем 'бесконечную' длину файла
        self._write_header(init_length)

    def close(self):
        try:
            super().close()
        except BrokenPipeError:
            pass


class _StreamPipe:
    def __init__(self):
        self._pipe = deque()
        self._event = threading.Event()
        self._closed = False

    def read(self) -> bytes:
        while True:
            self._event.wait(1)
            try:
                return self._pipe.popleft()
            except IndexError:
                if self._closed:
                    return b''
                else:
                    self._event.clear()

    def write(self, data: bytes):
        self._pipe.append(data)
        self._event.set()

    def end(self):
        self.write(b'')
        self._closed = True

    def close(self):
        pass

    def flush(self):
        pass

    @staticmethod
    def tell():
        return 0


class _StreamPopen(threading.Thread):
    OUT_CHUNK_SIZE = 1024 * 4
    POPEN_TIMEOUT = 10
    JOIN_TIMEOUT = 10

    def __init__(self, cmd):
        super().__init__()
        self._popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE)
        self._stream = _StreamPipe()
        self._closed = False
        self.start()

    def read(self) -> bytes:
        return self._stream.read()

    def write(self, data: bytes):
        self._popen.stdin.write(data)

    def run(self):
        while True:
            try:
                chunk = self._popen.stdout.read(self.OUT_CHUNK_SIZE)
            except ValueError:
                break
            if not chunk:
                break
            self._stream.write(chunk)

    def end(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._popen.stdin.close()
        except BrokenPipeError:
            pass
        try:
            self._popen.wait(self.POPEN_TIMEOUT)
        except subprocess.TimeoutExpired:
            pass
        self.join(timeout=self.JOIN_TIMEOUT)
        self._popen.stdout.close()
        self._popen.kill()
        self._stream.end()

    def close(self):
        pass

    def flush(self):
        pass

    @staticmethod
    def tell():
        return 0
