import importlib
from functools import lru_cache


@lru_cache()
def _wrapper():
    try:
        stt = importlib.import_module('lib.yandex_stt_service_interface')
    except ImportError as e:
        raise RuntimeError(e)
    return stt.stt


def yandex_stt_grpc(api_key: str, language_code: str, chunks) -> str:
    return _wrapper()(api_key, language_code, chunks)
