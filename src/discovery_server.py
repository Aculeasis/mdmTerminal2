import errno
import socket
import struct
import threading
import uuid

import logger


def lf_to_crlf(data: str) -> str:
    return CRLF.join(data.split('\n'))


CRLF = '\r\n'
TIMEOUT = 1.0
BUFFER_SIZE = 1024 * 2
M_SEARCH = b'M-SEARCH'
NOTIFY = b'NOTIFY'
SERVICE_NAME = 'mdmt2'
UUID = uuid.uuid3(uuid.UUID(int=uuid.getnode(), version=3), SERVICE_NAME)
SERVER_PORT = 7999

REPLY = lf_to_crlf('''HTTP/1.1 200 OK
CACHE-CONTROL:max-age=5000
ST:upnp:rootdevice
URI:{service}
USN:uuid:{uuid}
EXT:''').format(service=SERVICE_NAME, uuid=UUID) + CRLF
REPLY += lf_to_crlf('''Server:{server}
Location:http://{xml_url}/
AL:{location}''') + CRLF * 2

HTTP_HEADER_REPLY = lf_to_crlf('''HTTP/1.1 200 OK
Content-type: application/xml
Content-Length: {}''') + CRLF * 2
HTTP_XML_REPLY = lf_to_crlf('''<root>
    <specVersion>
        <major>1</major>
        <minor>0</minor>
    </specVersion>
    <device>
        <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
        <friendlyName>mdmTerminal2</friendlyName>
        <modelName>mdmTerminal2</modelName>
        <UDN>uuid:{0}</UDN>
        <modelNumber>{1}</modelNumber>
        <modelURL>https://github.com/Aculeasis/mdmTerminal2/</modelURL>
        <serviceList>
            <service>
                <URLBase>{2}:{3}</URLBase>
                <serviceType>urn:schemas-upnp-org:service:mdmTerminal2:1</serviceType>
                <serviceId>urn:schemas-upnp-org:serviceId:mdmTerminal2</serviceId>
                <eventSubURL/>
            </service>
        </serviceList>
    </device>
</root>''')


def server_init(sock: socket.socket, address: tuple):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(TIMEOUT)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass
    except socket.error as e:
        if e.errno != errno.ENOPROTOOPT:
            raise
    sock.bind(address)


class DiscoveryServer(threading.Thread):
    def __init__(self, cfg, log, ip='', port=1900, multicast_group='239.255.255.250'):
        super().__init__()
        self.cfg = cfg
        self.log = log
        self._address = (ip, port)
        self._work = False
        self._server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

        multicast_req = struct.pack('4sl', socket.inet_aton(multicast_group), socket.INADDR_ANY)
        self._server.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, multicast_req)
        self._http = UPNPServer(cfg, log, self._address)

    def start(self):
        try:
            server_init(self._server, self._address)
        except Exception as e:
            self.log('UDP binding error: {}'.format(e), logger.ERROR)
        else:
            self._work = True
            self._http.start()
            super().start()
            self.log('start', logger.INFO)

    def join(self, timeout=20):
        if self._work:
            self._work = False
            self.log('stopping...')
            super().join(timeout)
            self._server.close()
            self._http.join(timeout)
            self.log('stop.', logger.INFO)

    def run(self):
        def make_reply() -> bytes:
            ip = self.cfg.gts('ip')
            server = 'mdmTerminal2 version {}; uptime {} seconds'.format(self.cfg.version_str, self.cfg.uptime)
            location = '{}:{}'.format(ip, SERVER_PORT)
            xml_url = '{}:{}'.format(ip, self._address[1])
            return REPLY.format(server=server, xml_url=xml_url, location=location).encode()

        while self._work:
            try:
                msg, address = self._server.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                continue
            except socket.error as e:
                self.log('UDP socket error: {}'.format(e), logger.ERROR)
                continue
            if msg.startswith(M_SEARCH):
                try:
                    self._server.sendto(make_reply(), address)
                except Exception as e:
                    self.log('UDP reply sending error to {}:{}: {}'.format(*address, e), logger.WARN)
            elif not msg.startswith(NOTIFY):
                self.log('Wrong UDP request from {}:{}: {}'.format(*address, repr(msg.rstrip(b'\0'))))


class UPNPServer(threading.Thread):
    def __init__(self, cfg, log, address):
        super().__init__()
        self.cfg = cfg
        self.log = log
        self._address = address
        self._server = socket.socket()
        self._work = False

    def start(self):
        try:
            server_init(self._server, self._address)
        except Exception as e:
            self.log('TCP binding error {}:{}: {}'.format(*self._address, e), logger.ERROR)
        else:
            self._server.listen(1)
            self._work = True
            super().start()

    def join(self, timeout=20):
        if self._work:
            self._work = False
            super().join(timeout)
            self._server.close()

    def run(self):
        def make_reply() -> bytes:
            data = HTTP_XML_REPLY.format(UUID, self.cfg.version_str, self.cfg.gts('ip'), SERVER_PORT).encode()
            return HTTP_HEADER_REPLY.format(len(data)).encode() + data

        def read() -> bytes:
            try:
                return conn.recv(128)
            except OSError:
                return b''

        def send_xml():
            try:
                conn.sendall(make_reply())
            except socket.timeout:
                pass
            except Exception as e:
                self.log('HTTP reply sending error to {}:{}: {}'.format(*address, e))

        while self._work:
            try:
                conn, address = self._server.accept()
                conn.settimeout(2.0)
            except socket.timeout:
                continue
            try:
                if read().startswith(b'GET / '):
                    send_xml()
            finally:
                conn.close()
