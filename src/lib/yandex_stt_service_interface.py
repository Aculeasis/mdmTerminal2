# https://cloud.yandex.ru/docs/speechkit/stt/streaming

from functools import lru_cache

import grpc

from lib import yandex_stt_service_pb2
from lib import yandex_stt_service_pb2_grpc


@lru_cache()
def get_stub():
    cred = grpc.ssl_channel_credentials()
    channel = grpc.secure_channel('stt.api.cloud.yandex.net:443', cred)
    stub = yandex_stt_service_pb2_grpc.SttServiceStub(channel)
    return stub


def gen(language_code, chunks):
    # Задаем настройки распознавания.
    specification = yandex_stt_service_pb2.RecognitionSpec(
        language_code=language_code,
        profanity_filter=False,
        model='general',
        partial_results=False,
        audio_encoding='LINEAR16_PCM',
        sample_rate_hertz=16000
    )
    streaming_config = yandex_stt_service_pb2.RecognitionConfig(specification=specification)

    # Отправляем сообщение с настройками распознавания.
    yield yandex_stt_service_pb2.StreamingRecognitionRequest(config=streaming_config)

    for data in chunks:
        if not data:
            break
        yield yandex_stt_service_pb2.StreamingRecognitionRequest(audio_content=data)


def stt(api_key: str, language_code: str, chunks) -> str:
    stub = get_stub()
    it = stub.StreamingRecognize(
        gen(language_code, chunks),
        metadata=(('authorization', 'Api-Key {}'.format(api_key)),)
    )
    text = ''
    try:
        for r in it:
            try:
                if r.chunks[0].final:
                    text = r.chunks[0].alternatives[0].text
                    break
            except LookupError:
                pass
    # except grpc._channel._Rendezvous as e:
    except Exception as e:
        raise RuntimeError(e)
    return text
