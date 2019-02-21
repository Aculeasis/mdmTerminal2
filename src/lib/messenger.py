import queue
import threading


class Messenger(threading.Thread):
    def __init__(self):
        super().__init__(name='Messenger')
        self._queue = queue.Queue()
        self._work = True
        self.start()

    def call(self, call, callback, *args, **kwargs) -> bool:
        if not callable(call):
            return False
        callback = callback if callable(callback) else None
        self._queue.put_nowait((call, callback, args, kwargs))
        return True

    def join(self, timeout=30):
        if self._work:
            self._work = False
            self._queue.put_nowait(None)
            super().join(timeout)

    def run(self):
        while self._work:
            self._processing(self._queue.get())

    def _processing(self, data):
        if not data:
            return
        self._call(*data)

    @staticmethod
    def _call(call, callback, args, kwargs):
        result = call(*args, **kwargs)
        if callback:
            callback(result)
