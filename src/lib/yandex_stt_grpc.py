import importlib
from functools import lru_cache


@lru_cache()
def _wrapper():
    try:
        stt = importlib.import_module('lib.yandex_stt_service_interface')
    except ImportError as e:
        raise RuntimeError(e)
    return stt.stt


def yandex_stt_grpc(folder_id: str, iam_token: str, language_code: str, chunks) -> str:
    return _wrapper()(folder_id, iam_token, language_code, chunks)
