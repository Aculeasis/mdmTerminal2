
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


_client = {}
_lock = threading.Lock()


def aws_boto3(key, **kwargs):
    global _lock
    with _lock:
        if key not in _client:
            _create_session(key)
        return AWS(client=_client[key], **kwargs)


def _create_session(key):
    global _client
    try:
        boto3 = importlib.import_module('boto3')
    except (ImportError, ModuleNotFoundError) as e:
        raise RuntimeError('Error importing boto3: {}'.format(e))
    session = boto3.Session(aws_access_key_id=key[0], aws_secret_access_key=key[1], region_name=key[2])
    polly = session.client('polly')
    _client = {key: polly.synthesize_speech}
