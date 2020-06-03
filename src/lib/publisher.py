import queue
import threading


class PubSub(threading.Thread):
    def __init__(self):
        super().__init__(name='PubSub')
        # Подписки, формат `[канал][событие]: [список коллбэков]`
        self._event_callbacks = {}
        # Очередь вызовов, все вызовы и изменения подписок делаем в треде
        self._queue = queue.Queue()
        self.stopping = False
        self._unsubscribe_later = []
        self.start()

    def subscribe(self, event, callback, channel='default') -> bool:
        return self._subscribe_action('add_subscribe', event, callback, channel)

    def unsubscribe(self, event, callback, channel='default') -> bool:
        return self._subscribe_action('remove_subscribe', event, callback, channel)

    def registration(self, event: str, channel='default'):
        if not (isinstance(event, str) and event and channel):
            return None
        return lambda *args, **kwargs: self._call(channel, event, *args, **kwargs)

    def has_subscribers(self, event: str, channel='default') -> bool:
        return event in self._event_callbacks.get(channel, {})

    def events_list(self, channel='default') -> list:
        return list(self._event_callbacks.get(channel, {}).keys())

    def call(self, name, *args, **kwargs):
        # Внешний вызов, канал default
        self._queue.put_nowait(('default', name, args, kwargs))

    def sub_call(self, channel: str, event: str, *args, **kwargs):
        self._queue.put_nowait((channel, event, args, kwargs))

    def _call(self, channel, name, *args, **kwargs):
        self._queue.put_nowait((channel, name, args, kwargs))

    def join(self, timeout=30):
        self._queue.put_nowait(None)
        super().join(timeout=timeout)

    def run(self):
        while self._processing(self._queue.get()):
            pass

    def report(self):
        while self._unsubscribe_later:
            self._remove_subscribe(*self._unsubscribe_later.pop(0))
        if self._event_callbacks:
            print('PubSub orphans:', self._event_callbacks)

    def _processing(self, data) -> bool:
        if isinstance(data, tuple):
            self._call_processing(*data)
        elif isinstance(data, list):
            (cmd, channel, data) = data
            if cmd == 'add_subscribe':
                self._add_subscribe(data, channel)
            elif cmd == 'remove_subscribe':
                if self.stopping:
                    self._unsubscribe_later.append((data, channel))
                else:
                    self._remove_subscribe(data, channel)
            else:
                raise RuntimeError('Wrong command: {}, {}'.format(repr(cmd), repr(data)))
        elif data is None:
            return False
        else:
            raise RuntimeError('Wrong type of data: {}'.format(repr(data)))
        return True

    def _call_processing(self, channel, name, args, kwargs):
        # Вызываем подписчиков
        if channel in self._event_callbacks and name in self._event_callbacks[channel]:
            for callback in self._event_callbacks[channel][name]:
                callback(name, *args, **kwargs)

    def _add_subscribe(self, data, channel):
        # Добавляем подписчиков
        if channel not in self._event_callbacks:
            self._event_callbacks[channel] = {}
        for name, callback in data:
            if name not in self._event_callbacks[channel]:
                self._event_callbacks[channel][name] = set()
            self._event_callbacks[channel][name].add(callback)

    def _remove_subscribe(self, data, channel):
        # Удаляем подписчиков
        for name, callback in data:
            if name not in self._event_callbacks.get(channel, {}):
                continue
            self._event_callbacks[channel][name].discard(callback)
            if not self._event_callbacks[channel][name]:
                del self._event_callbacks[channel][name]
            if not self._event_callbacks[channel]:
                del self._event_callbacks[channel]

    def _subscribe_action(self, cmd, event, callback, channel) -> bool:
        if isinstance(event, (list, tuple)) and isinstance(callback, (list, tuple)):
            # Так нельзя
            return False
        if not (isinstance(event, (list, tuple, str)) and event and callback and channel):
            # И так нельзя
            return False
        if isinstance(event, (list, tuple)):
            data = [(key, callback) for key in event if key]
        elif isinstance(callback, (list, tuple)):
            data = [(event, key) for key in callback if key]
        else:
            data = [(event, callback)]
        if data:
            self._queue.put_nowait([cmd, channel, data])
            return True
        return False
