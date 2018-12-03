
import importlib
import threading


class AWS:
    def __init__(self, text, speaker, audio_format, client, lang, *_, **__):
        if not text:
            raise RuntimeError('No text to speak')
        params = {
            'OutputFormat': audio_format,
            'Text': text,
            'LanguageCode': lang,
            'VoiceId': speaker
        }
        try:
            self._data = client(**params)['AudioStream']
        except Exception as e:
            raise RuntimeError('{}: {}'.format(type(e).__name__, e))

    def iter_me(self):
        try:
            for chunk in self._data.iter_chunks():
                yield chunk
        except Exception as e:
            raise RuntimeError('{}: {}'.format(type(e).__name__, e))

    def stream_to_fps(self, fps):
        if not isinstance(fps, list):
            fps = [fps]
        for chunk in self.iter_me():
            for f in fps:
                f.write(chunk)

    def save(self, file_path):
        with open(file_path, 'wb') as fp:
            self.stream_to_fps(fp)
        return file_path


class _SessionStorage:
    def __init__(self):
        self._client = {}
        self._lock = threading.Lock()

    def _create_session(self, key):
        try:
            boto3 = importlib.import_module('boto3')
        except (ImportError, ModuleNotFoundError) as e:
            raise RuntimeError('Error importing boto3: {}'.format(e))
        session = boto3.Session(aws_access_key_id=key[0], aws_secret_access_key=key[1], region_name=key[2])
        polly = session.client('polly')
        self._client = {key: polly.synthesize_speech}

    def __call__(self, key, **kwargs):
        with self._lock:
            if key not in self._client:
                self._create_session(key)
            return AWS(client=self._client[key], **kwargs)


aws_boto3 = _SessionStorage()
