import threading
import subprocess
import time

CMD = {
    '.mp3': ['mpg123', '-q'],
    '.wav': ['aplay', '-q'],
    '.opus': ['opusdec', '--quiet', '--force-wav', '-', '-']
}
BACKENDS = {
    # mplayer ведет себя странно
    # 'mplayer': ['mplayer', '-really-quiet', '-noautosub', '-novideo', '-cache', '512', '-cache-min', '30'],
    'mpv': ['mpv', '--really-quiet', '--no-video', '-cache', '512'],
}


class StreamPlayer(threading.Thread):
    def __init__(self, popen, fp):
        super().__init__()
        self._fp = fp
        self._popen = popen
        self.poll = self._popen.poll
        self.wait = self._popen.wait
        self.start()

    def kill(self):
        self._fp.write(b'')
        self._popen.kill()
        if self.is_alive():
            super().join()

    def run(self):
        data = self._fp.read()
        while data and self.poll() is None:
            try:
                self._popen.write(data)
            except BrokenPipeError:
                # FIXME: Иногда aplay падает без видимой причины
                # aplay: xrun:1624: read/write error, state = RUNNING
                # Скорее всего это аппаратная проблема или проблема паузы между чанками
                # На всякий случай я увеличу размер чанка при стриминге wav до 4 KiB, но это не сильно помогает
                break
            data = self._fp.read()
        self._popen.close()


class Popen(threading.Thread):
    def __init__(self, cmd, callback):
        self._one = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.poll = self._one.poll
        self.write = self._one.stdin.write
        self.kill = self._one.kill
        self.wait = self._one.wait
        if callback:
            super().__init__()
            self._callback = callback
            self.start()

    def run(self):
        self.wait()
        self._callback(False)

    def close(self):
        try:
            self._one.stdin.close()
        except BrokenPipeError:
            pass
        try:
            self._one.stderr.close()
        except BrokenPipeError:
            pass


class DoublePopen(threading.Thread):
    # Я не нашел простой плеер для опуса, так что будем коннектить два субпроцесса
    # В первом декоред opus -> wav, во втором aplay
    # FIXME: opusdec зомбируется, но потом помирает. Может его килять принудительно?
    def __init__(self, cmd1, cmd2, callback):
        self._one = subprocess.Popen(cmd1, stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        self._two = subprocess.Popen(cmd2, stdin=self._one.stdout, stderr=subprocess.PIPE)
        self.write = self._one.stdin.write
        if callback:
            super().__init__()
            self._callback = callback
            self.start()

    def run(self):
        self._two.wait()
        self._callback(False)

    def poll(self):
        if self._one.poll() is None or self._two.poll() is None:
            return
        return self._one.poll() or self._two.poll()

    def kill(self):
        self._one.kill()
        self._two.kill()

    def wait(self, timeout=None):
        end = time.time()
        self._one.wait(timeout)
        if timeout is None:
            self._two.wait(timeout)
        else:
            end = timeout - (time.time() - end)
            if end > 0:
                self._two.wait(end)

    def close(self):
        for target in (self._one.stdin, self._one.stdout, self._one.stderr, self._two.stderr):
            try:
                target.close()
            except BrokenPipeError:
                pass


def _select_popen(cmd1, cmd2, callback):
    return Popen(cmd2, callback) if cmd1 is None else DoublePopen(cmd1, cmd2, callback)


def _get_cmd2(ext, path):
    cmd = CMD[ext].copy()
    cmd.append(path)
    return cmd


def _get_cmd1(path):
    cmd = CMD['.opus'].copy()
    cmd[-2] = path
    return cmd


def get_popen(ext, fp_or_file, stream, callback, backend=None):
    file_path = '-' if stream else fp_or_file
    if backend in BACKENDS:
        cmd1 = None
        cmd2 = BACKENDS[backend].copy()
        cmd2.append(file_path)
    elif ext == '.opus':
        cmd1 = _get_cmd1(file_path)
        cmd2 = _get_cmd2('.wav', '-')
    else:
        cmd1 = None
        cmd2 = _get_cmd2(ext, file_path)
    if stream:
        return StreamPlayer(_select_popen(cmd1, cmd2, callback), fp_or_file)
    else:
        return _select_popen(cmd1, cmd2, callback)
