
import logger
from lib.socket_api_handler import Unlock
from lib.socket_wrapper import Connect


class UpgradeDuplexHandshake:
    """
    -> upgrade duplex

    # optional
    <- login
    -> login ******

    # optional
    <- password
    -> password ******

    <- upgrade duplex ok
    sometimes:
    <-> say say any
    <-> broken broken handshake

    """
    def __init__(self, cfg, log, own, conn: Connect, incoming=True):
        self.log = log
        self.own = own
        self.conn = conn
        self._incoming = incoming
        self.stage = 0
        self._success = False
        self._allow = True
        # dict or cfg?
        if 'smarthome' in cfg and isinstance(cfg['smarthome'], dict):
            cfg = cfg['smarthome']
        self.username = cfg.get('username', '')
        self.password = cfg.get('password', '')
        self.address = (self.conn.ip, self.conn.port)
        if incoming:
            self.__call__('upgrade duplex')
        else:
            self.log('=== Start handshake {}:{} ==='.format(*self.address), logger.INFO)
            self.send('upgrade duplex')

    @property
    def success(self) -> bool:
        return self._success

    def end(self):
        self._allow = False
        self.send(b'')

    def broken(self, msg=''):
        if msg:
            msg = 'BROKEN {} {}'.format(self.stage, msg)
            self.send(msg)
            self.log(msg, logger.WARN)
        self.log('=== Broke handshake {}:{} ==='.format(*self.address), logger.WARN)
        self.end()

    def get_broken(self, msg: str):
        self.log('Received: {}'.format(msg), logger.WARN)
        self.log('=== Broke handshake {}:{} ==='.format(*self.address), logger.WARN)
        self.end()

    def say(self, line: str):
        self.log('SAY: {}'.format(line[3:].lstrip()), logger.INFO)

    def send(self, data):
        try:
            if self._allow:
                self.conn.write(data)
        except RuntimeError as e:
            self.log('Socket error: {}'.format(e), logger.ERROR)
            self._allow = False

    def _upgrade(self):
        self._allow = False
        cmd = 'upgrade duplex'
        if self.own.has_subscribers(cmd, cmd):
            self._success = True
            self.log('===== End handshake {}:{} ==='.format(*self.address), logger.INFO)
            lock = Unlock()
            self.own.sub_call(cmd, cmd, 'upgrade duplex ok' if self._incoming else '', lock, self.conn)
            lock.wait(30)
        else:
            self.broken('NO SUBSCRIBERS {}'.format(cmd))

    def __call__(self, line: str):
        if not self._allow:
            return
        line_l = line.lower()
        if self._incoming:
            self._parse_incoming(line, line_l)
        else:
            self._parse_outgoing(line, line_l)

    def outgoing(self):
        reading = False
        for line in self.conn.read():
            reading = True
            self.__call__(line)
        if self._allow and reading:
            self.broken('UNSUCCESSFULLY')
        self._allow = False
        if not reading:
            self.broken('Server not responding')

    def _parse_incoming(self, line: str, line_l: str):
        def split_line(line_: str) -> str:
            line_ = line_.split(' ', 1)
            return line_[1] if len(line_) == 2 else ''

        if not self.stage and line_l == 'upgrade duplex':
            self.log('=== Start handshake {}:{} ==='.format(*self.address), logger.INFO)
            if self.username:
                self.send('LOGIN')
                self.stage = 1
            elif self.password:
                self.send('PASSWORD')
                self.stage = 2
            else:
                self._upgrade()
        elif self.stage == 1 and line_l.startswith('login'):
            login = split_line(line)
            if self.username and self.username != login:
                self.broken('WRONG LOGIN {}'.format(login))
            elif self.password:
                self.send('PASSWORD')
                self.stage = 2
            else:
                self._upgrade()
        elif self.stage == 2 and line_l.startswith('password'):
            password = split_line(line)
            if not password or password != self.password:
                self.broken('WRONG PASSWORD')
                return
            self._upgrade()
        else:
            self._others(line, line_l)

    def _parse_outgoing(self, line: str, line_l: str):
        if line_l == 'upgrade duplex ok':
            self._upgrade()
        elif line_l == 'login' and not self.stage:
            self.stage = 1
            self.send('LOGIN {}'.format(self.username))
        elif line_l == 'password' and self.stage < 2:
            self.stage = 2
            self.send('PASSWORD {}'.format(self.password))
        else:
            self._others(line, line_l)

    def _others(self, line: str, line_l: str):
        if line_l.startswith('broken'):
            self.get_broken(line)
        elif line_l.startswith('say'):
            self.say(line)
        else:
            self.broken('SURPRISE {}'.format(line))
