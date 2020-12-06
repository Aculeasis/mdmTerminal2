# The MIT License (MIT)
#
# gTTS: Copyright © 2014-2018 Pierre Nicolas Durette
# https://github.com/pndurette/gTTS
#
# This code was modified by Aculeasis, 2020

import re
import base64

import gtts
import requests
import urllib3
from gtts.tts import log, gTTSError

from .proxy import proxies


# TODO: Следить за актуальностью копипаст

try:
    _version = tuple(int(x) for x in gtts.__version__.split('.'))
except (TypeError, ValueError):
    _version = (0, 0, 0)


class FPBranching:
    def __init__(self, fps):
        self._fps = fps if isinstance(fps, (list, tuple)) else [fps]

    def write(self, data):
        for fp in self._fps:
            fp.write(data)


class Google(gtts.gTTS):
    def __init__(self, text, buff_size, lang='en', slow=False, *_, **__):
        super().__init__(text=text, lang=lang, slow=slow, lang_check=False)
        self._buff_size = buff_size
        if _version >= (2, 2, 0):
            self.write_to_fp = self.write_to_fp_221

    def stream_to_fps(self, fps):
        self.write_to_fp(FPBranching(fps))

    # part of https://github.com/pndurette/gTTS/blob/v2.2.1/gtts/tts.py#L243
    def write_to_fp_221(self, fp):
        """Do the TTS API request(s) and write bytes to a file-like object.
        Args:
            fp (file object): Any file-like object to write the ``mp3`` to.
        Raises:
            :class:`gTTSError`: When there's an error with the API request.
            TypeError: When ``fp`` is not a file-like object that takes bytes.
        """
        # When disabling ssl verify in requests (for proxies and firewalls),
        # urllib3 prints an insecure warning on stdout. We disable that.
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        prepared_requests = self._prepare_requests()
        for idx, pr in enumerate(prepared_requests):
            try:
                with requests.Session() as s:
                    # Send request
                    r = s.send(request=pr,
                               # proxies=urllib.request.getproxies(),
                               proxies=proxies('tts_google'),
                               verify=False)

                log.debug("headers-%i: %s", idx, r.request.headers)
                log.debug("url-%i: %s", idx, r.request.url)
                log.debug("status-%i: %s", idx, r.status_code)

                r.raise_for_status()
            except requests.exceptions.HTTPError as e:  # pragma: no cover
                # Request successful, bad response
                log.debug(str(e))
                raise gTTSError(tts=self, response=r)
            except requests.exceptions.RequestException as e:  # pragma: no cover
                # Request failed
                log.debug(str(e))
                raise gTTSError(tts=self)

            try:
                # Write
                # for line in r.iter_lines(chunk_size=1024):
                for line in r.iter_lines(chunk_size=self._buff_size):
                    decoded_line = line.decode('utf-8')
                    if 'jQ1olc' in decoded_line:
                        audio_search = re.search(r'jQ1olc","\[\\"(.*)\\"]', decoded_line)
                        if audio_search:
                            as_bytes = audio_search.group(1).encode('ascii')
                            decoded = base64.b64decode(as_bytes)
                            fp.write(decoded)
                        else:
                            # Request successful, good response,
                            # no audio stream in response
                            raise gTTSError(tts=self, response=r)
                log.debug("part-%i written to %s", idx, fp)
            except (AttributeError, TypeError) as e:
                raise TypeError(
                    "'fp' is not a file-like object or it does not take bytes: %s" %
                    str(e))
