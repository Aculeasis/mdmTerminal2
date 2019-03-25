from ipaddress import ip_address, ip_network


class _InterfaceStorage:
    def __init__(self, interfaces):
        if not isinstance(interfaces, (list, tuple, set)):
            interfaces = [interfaces]
        self._store = tuple(interfaces)
        self._empty = not bool(self._store)

    def __contains__(self, item: str):
        if self._empty:
            return True
        try:
            item = ip_address(item)
        except ValueError:
            return False
        for interface in self._store:
            if item == interface:
                return True
        return False

    def __str__(self):
        return ', '.join(str(x) for x in self._store) if not self._empty else 'ANY'


class _Interface:
    def __init__(self, address: str):
        self._network = False
        if not address:
            raise ValueError('Empty data')
        elif '/' in address:
            self._i = ip_network(address)
            self._network = True
        else:
            self._i = ip_address(address)

    def __eq__(self, other):
        if self._network:
            return other in self._i
        return other == self._i

    def __str__(self):
        return str(self._i)


def make_interface_storage(ips: str) -> _InterfaceStorage:
    ips = [ip.strip() for ip in ips.split(',')]
    interfaces = []
    for ip in ips:
        if not ip:
            continue
        try:
            interfaces.append(_Interface(ip))
        except ValueError as e:
            raise RuntimeError('Wrong IP or Network {}: {}'.format(repr(ip), e))
    return _InterfaceStorage(interfaces)
