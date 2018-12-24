import queue
import threading


class PubSub(threading.Thread):
    def __init__(self):
        super().__init__(name='PubSub')
        # Подписки, формат `событие: [список коллбэков]`
        self._event_callbacks = {}
        # Очередь вызовов, все вызовы и изменения подписок делаем в треде
        self._queue = queue.Queue()
        self._work = False

    def subscribe(self, event, callback) -> bool:
        return self._subscribe_action('add_subscribe', event, callback)

    def unsubscribe(self, event, callback) -> bool:
        return self._subscribe_action('remove_subscribe', event, callback)

    def registration(self, event: str):
        if not isinstance(event, str) or not event:
            return None
        return lambda *args, **kwargs: self.call(event, *args, **kwargs)

    def call(self, name, *arg, **kwarg):
        # Внешний вызов, для registration или дефолтных событий
        self._queue.put_nowait((name, arg, kwarg))

    def start(self):
        if not self._work:
            self._work = True
            super().start()

    def join(self, timeout=None):
        if self._work:
            self._work = False
            self._queue.put_nowait(None)
            super().join(timeout)

    def run(self):
        while self._work:
            data = self._queue.get()
            if data is None:
                break
            if isinstance(data, tuple):
                self._call_processing(*data)
            elif isinstance(data, list):
                cmd, data = data[0], data[1]
                if cmd == 'add_subscribe':
                    self._add_subscribe(data)
                elif cmd == 'remove_subscribe':
                    self._remove_subscribe(data)
                else:
                    raise RuntimeError('Wrong command: {}, {}'.format(repr(cmd), repr(data)))
            else:
                raise RuntimeError('Wrong type of data: {}'.format(repr(data)))

    def _call_processing(self, name, arg, kwarg):
        # Вызываем подписчиков
        if name in self._event_callbacks:
            for callback in self._event_callbacks[name]:
                callback(name, *arg, **kwarg)

    def _add_subscribe(self, data):
        # Добавляем подписчиков
        for name, callback in data:
            if name not in self._event_callbacks:
                self._event_callbacks[name] = set()
            self._event_callbacks[name].add(callback)

    def _remove_subscribe(self, data):
        # Удаляем подписчиков
        for name, callback in data:
            if name not in self._event_callbacks:
                continue
            self._event_callbacks[name].discard(callback)
            if not self._event_callbacks[name]:
                del self._event_callbacks[name]

    def _subscribe_action(self, cmd, event, callback) -> bool:
        if isinstance(event, (list, tuple)) and isinstance(callback, (list, tuple)):
            # Так нельзя
            return False
        if not (isinstance(event, (list, tuple, str)) and event and callback):
            # И так нельзя
            return False
        if isinstance(event, (list, tuple)):
            data = [(key, callback) for key in event if key]
        elif isinstance(callback, (list, tuple)):
            data = [(event, key) for key in callback if key]
        else:
            data = [(event, callback)]
        if data:
            self._queue.put_nowait([cmd, data])
            return True
        return False
