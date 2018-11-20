import requests

from utils import REQUEST_ERRORS


class MajordomoRequests:
    def __init__(self, cfg):
        self._cfg = cfg

    @property
    def ip_set(self):
        return True if self._cfg.get('ip') else False

    def send(self, qry):
        # Отправляет сообщение на сервер мжд, возвращает url запроса или кидает RuntimeError
        # На основе https://github.com/sergejey/majordomo-chromegate/blob/master/js/main.js#L196

        terminal = self._cfg.get('terminal')
        username = self._cfg.get('username')
        password = self._cfg.get('password')
        url = 'http://{}/command.php'.format(self._cfg.get('ip', ''))

        auth = (username, password) if username and password else None
        params = dict(qry=qry)
        if terminal:
            params['terminal'] = terminal
        if username:
            params['username'] = username
        try:
            reply = requests.get(url, params=params, auth=auth)
        except REQUEST_ERRORS as e:
            raise RuntimeError(e)
        if not reply.ok:
            raise RuntimeError('Request error {}: {}'.format(reply.status_code, reply.reason))
        return reply.request.url
