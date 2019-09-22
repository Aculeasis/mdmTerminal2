import mimetypes
import urllib.parse
from xml.etree import ElementTree

import requests


class Error(Exception):
    pass


class MediaRender:
    # FIXME: # gmediarender глючит при volume -> pause(0) и не сразу понижает громкость, мб это фича
    MAX_FAILURES = 5
    STATE_FIX = {
        'PLAYING': 'play',
        'STOPPED': 'stop',
        'PAUSED_PLAYBACK': 'pause',
        'NO_MEDIA_PRESENT': 'stop'
    }

    def __init__(self, data: dict):
        self._data = data
        self.broken = not (self._data and isinstance(data, dict))
        self._failures = 0
        self.log_cb = None

    @property
    def pretty_name(self):
        return '{}[{}]'.format(self._data['name'], self._data['url']) if self._data else 'Wrong data'

    def pause(self, mode=None):
        if self.broken:
            return
        if mode is None:
            mode = 1 if self.state() == 'play' else 0
        if not mode:

            self._send_request('AVTransport', 'Play', Speed=1)
        else:
            self._send_request('AVTransport', 'Pause')

    @property
    def volume(self):
        if self.broken:
            return -1
        r = self._send_request('RenderingControl', 'GetVolume', Channel='Master')
        return self._parse_response(r, 'CurrentVolume', -1)

    @volume.setter
    def volume(self, val):
        if self.broken:
            return
        self._send_request('RenderingControl', 'SetVolume', DesiredVolume=val)

    def state(self) -> str:
        # STOPPED, PLAYING, TRANSITIONING, PAUSED_PLAYBACK, PAUSED_RECORDING, RECORDING, NO_MEDIA_PRESENT, CUSTOM;
        state = 'stop'
        if self.broken:
            return state
        r = self._send_request('AVTransport', 'GetTransportInfo')
        state = self._parse_response(r, 'CurrentTransportState', state)
        return self.STATE_FIX.get(state, state)

    def currentsong(self) -> dict:
        # TODO
        if self.broken:
            return {'title': 'broken', 'artist': 'broken'}
        return {'title': 'notimplemented', 'artist': 'notimplemented'}

    def play(self, uri):
        if self.broken or not uri:
            return
        m_data = '&lt;DIDL-Lite xmlns=&quot;urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/&quot; xmlns:dc=&quot;' \
                 'http://purl.org/dc/elements/1.1/&quot; xmlns:sec=&quot;http://www.sec.co.kr/&quot; ' \
                 'xmlns:upnp=&quot;urn:schemas-upnp-org:metadata-1-0/upnp/&quot;&gt;' \
                 '&lt;item id=&quot;0&quot; parentID=&quot;-1&quot; restricted=&quot;false&quot;&gt;&lt;' \
                 'res protocolInfo=&quot;http-get:*:{type}:*&quot;&gt;{uri}&lt;/res&gt;&lt;/item&gt;&lt;/DIDL-Lite&gt' \
                 ';'.format(uri=uri, type=self._get_content_type(uri))

        self._send_request('AVTransport', 'Stop')
        self._send_request('AVTransport', 'SetAVTransportURI', CurrentURI=uri, CurrentURIMetaData=m_data)
        self._send_request('AVTransport', 'Play', Speed=1)

    def _log(self, msg):
        if self.log_cb:
            self.log_cb(msg)

    def _send_request(self, transport, cmd, **args) -> str:
        # https://github.com/sergejey/majordomo/blob/4096837c1c65dee65d3b9419096b1aa612cce39f/modules/app_player/libs/MediaRenderer/MediaRenderer.php#L96
        args['InstanceID'] = args.get('InstanceID', 0)
        body = '<?xml version="1.0" encoding="utf-8" standalone="yes"?>\r\n' \
               '<s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" ' \
               'xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">' \
               '<s:Body><u:{cmd} xmlns:u="{type}">{args}</u:{cmd}></s:Body>' \
               '</s:Envelope>'.format(
                cmd=cmd, type=self._data[transport]['type'],
                args=''.join('<{0}>{1}</{0}>'.format(key, val) for key, val in args.items())
                ).encode()
        headers = {
            'Host': self._data['url'],
            'Content-Type': 'text/xml; charset="utf-8"',
            'Content-Length': str(len(body)),
            'SOAPAction': '"{}#{}"'.format(self._data[transport]['type'], cmd)
        }
        try:
            r = requests.post(self._data[transport]['url'], headers=headers, data=body, verify=False)
            if not r.ok:
                r.raise_for_status()
        except Exception as e:
            self._failures += 1
            msg = 'Media Render error: {}'.format(e)
            if self._failures > self.MAX_FAILURES:
                raise Error(msg)
            self._log(msg)
            return ''
        else:
            self._failures = 0
            return r.text

    @staticmethod
    def _get_content_type(uri):
        # noinspection PyBroadException
        try:
            type_ = requests.head(uri).headers.get('Content-Type', 'application/octet-stream')
            if type_ == 'application/octet-stream':
                type_ = mimetypes.guess_type(urllib.parse.urlparse(uri).path)[0]
                type_ = 'audio/mpeg' if not type_ or type_ == 'application/octet-stream' else type_
        except Exception:
            return 'audio/mpeg'
        return type_

    def _parse_response(self, r: str, tag: str, default):
        if r:
            try:
                root = ElementTree.fromstring(r)[0][0]
            except (IndexError, ElementTree.ParseError) as e:
                self._log('Reply parsing error: {}'.format(e))
                return default
            el = root.find(tag)
            if el is not None:
                return el.text
        return default
