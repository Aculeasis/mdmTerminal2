from functools import lru_cache


@lru_cache()
def _wrapper():
    try:
        from lib.yandex.stt_service_interface import stt
        return stt
    except ImportError as e:
        raise RuntimeError(e)


def yandex_stt_grpc(api_key: str, language_code: str, chunks) -> str:
    return _wrapper()(api_key, language_code, chunks)
