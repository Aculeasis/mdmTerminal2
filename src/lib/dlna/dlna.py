import socket
import struct
import time
import urllib.parse
from xml.etree import ElementTree

import requests

from lib.dlna.media_render import Error, MediaRender
from utils import server_init

M_SEARCH = b'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\nST: ' \
            b'urn:schemas-upnp-org:device:MediaRenderer\r\nUSER-AGENT: \r\n\r\n '
M_GROUP = '239.255.255.250'
M_PORT = 1900
BUFFER_SIZE = 1024 * 2
LISTEN_PORT = 25500
TIMEOUT = 0.3
WAIT = 4


def find_MediaRenderer(name=None, ip=None,) -> MediaRender:
    data = UPNPScan()
    if not data:
        raise Error('MediaRender\'s not found')

    def by_key(key, val):
        for render in data:
            if render[key] == val:
                return render
        return None
    found = None
    if name:
        found = by_key('name', name)
    if not found and ip:
        found = by_key('ip', ip)
    if not found:
        msg = 'No matches found (candidates: {})'.format(', '.join('{}[{}]'.format(k['name'], k['ip']) for k in data))
        raise Error(msg)
    return MediaRender(found)


def UPNPScan() -> tuple:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as server:
        multicast_req = struct.pack('4sl', socket.inet_aton(M_GROUP), socket.INADDR_ANY)
        server.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, multicast_req)
        server_init(server, ('', LISTEN_PORT), TIMEOUT)
        return scan(server)


def get_location(msg: bytes) -> str:
    location = ''
    for line in msg.split(b'\r\n')[1:]:
        el = line.split(b':', maxsplit=1)
        if len(el) == 2 and el[0].upper() == b'LOCATION':
            location = el[1].decode().lstrip(' ').strip('"')
            break
    return location


def get_render_info(location: str) -> dict or None:
    def parse_service(srv):
        to_find = ('serviceId', 'serviceType', 'controlURL')
        find = {}
        for el in srv:
            for k in to_find:
                if el.tag.endswith(k):
                    find[k] = el.text
                    break
            if len(find) == 3:
                return [find[k] for k in to_find]
        return [None] * 3

    data = {
        'url': None,
        'ip': None,
        'name': None,
        'AVTransport': None,
        'RenderingControl': None
    }
    root = ElementTree.fromstring(requests.get(location).content)

    device = None
    for child in root:
        if child.tag.endswith('URLBase'):
            data['url'] = child.text
        elif child.tag.endswith('device'):
            device = child
        if data['url'] and device:
            break
    if not device:
        return None

    if not data['url']:
        addr = urllib.parse.urlparse(location)
        data['url'] = '{}://{}:{}'.format(addr.scheme, addr.hostname, addr.port)

    data['url'] = data['url'].rstrip('/')
    data['ip'] = urllib.parse.urlparse(data['url']).hostname

    services = None
    for child in device:
        if child.tag.endswith('friendlyName'):
            data['name'] = child.text
        elif child.tag.endswith('serviceList'):
            services = child
        if data['name'] and services:
            break
    if not services:
        return None
    data['name'] = data['name'] or data['ip']

    filling = {
        'urn:upnp-org:serviceId:AVTransport': 'AVTransport',
        'urn:upnp-org:serviceId:RenderingControl': 'RenderingControl'
    }
    for child in services:
        name, type_name, url = parse_service(child)
        if name in filling:
            data[filling[name]] = {
                'url':  '{}{}'.format(data['url'], url),
                'type': type_name
            }
        if all(data[k] for k in filling.values()):
            break
    else:
        return None
    return data


def scan(sock: socket.socket) -> tuple:
    data = []
    unique = set()
    sock.sendto(M_SEARCH, (M_GROUP, M_PORT))
    stop_time = time.time() + WAIT
    while time.time() < stop_time:
        try:
            msg, address = sock.recvfrom(BUFFER_SIZE)
        except socket.timeout:
            continue
        msg = msg.rstrip(b'\0')
        # noinspection PyBroadException
        try:
            info = get_render_info(get_location(msg))
            if info:
                id_ = info['AVTransport']['url'] + info['RenderingControl']['url']
                if id_ not in unique:
                    data.append(info)
                    unique.add(id_)
        except Exception as _:
            pass
    return tuple(data)
