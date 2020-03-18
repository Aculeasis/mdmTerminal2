#!/usr/bin/env python3

import queue
import threading
import time
from collections import OrderedDict
from uuid import uuid4

import logger
from lib.api.api import API
from lib.api.misc import api_commands
from lib.socket_wrapper import Connect
from lib.subscriptions_worker import SubscriptionsWorker
from owner import Owner
from utils import pretty_time


class DuplexPool(threading.Thread):
    UPGRADE_DUPLEX = 'upgrade duplex'

    def __init__(self, cfg, log, owner: Owner):
        super().__init__(name='DuplexPool')
        self.cfg = cfg
        self.log = log
        self.own = owner
        self._queue = queue.Queue()
        self._pool = OrderedDict()
        self._pool_size = None
        self.work = False
        self.own.subscribe(self.UPGRADE_DUPLEX, self._handle_upgrade_duplex, self.UPGRADE_DUPLEX)

    def start(self) -> None:
        self.work = True
        super().start()
        self.log('start', logger.INFO)

    def close_signal(self):
        self.own.unsubscribe(self.UPGRADE_DUPLEX, self._handle_upgrade_duplex, self.UPGRADE_DUPLEX)

    def join(self, timeout=30) -> None:
        self.close_signal()
        self._queue.put_nowait((None, None))
        super().join(timeout=timeout)

    def reload(self):
        if self.work:
            self._queue.put_nowait(('reload', None))

    def _handle_upgrade_duplex(self, _, cmd, lock, conn):
        try:
            conn_ = conn.extract()
            if conn_:
                self._queue.put_nowait(('add', conn_, cmd))
                if not self.work:
                    self.start()
        finally:
            lock()

    def _set_pool_size(self):
        self._pool_size = self.cfg.gt('smarthome', 'pool_size')
        if self._pool_size < 0:
            self._pool_size = 0

    @staticmethod
    def _no_conn(conn: Connect, cmd):
        if cmd:
            try:
                conn.write({'error': {'code': -9999, 'message': 'disabled'}, 'id': cmd})
            except RuntimeError:
                pass
        try:
            conn.close()
        except RuntimeError:
            pass

    def _add_worker(self, conn: Connect, cmd):
        if not self._pool_size:
            return self._no_conn(conn, cmd)
        self.log('New worker: {}::{}:{}'.format(*conn.info))
        id_ = '{}'.format(uuid4())
        name = '{}:{}'.format(*conn.info[1:])
        self._pool[id_] = DuplexInstance(
            self.cfg, self.log.add(name), self.own, name, conn, cmd, lambda: self._queue.put_nowait(('del', id_))
        )
        self._remove_overloads()

    def _del_worker(self, id_: str):
        worker = self._pool.pop(id_, None)
        if worker:
            self._kill_overloads([worker])

    def _reload(self):
        self._set_pool_size()
        self._remove_overloads()

    def _remove_overloads(self):
        pool = []
        while self._pool and len(self._pool) > self._pool_size:
            _, value = self._pool.popitem(False)
            pool.append(value)
        if pool:
            self._kill_overloads(pool)

    @staticmethod
    def _kill_overloads(pool: list):
        for target in pool:
            target.close_signal()
        for target in pool:
            time_ = time.time()
            target.join()
            time_ = time.time() - time_
            if target.is_alive():
                target.log('Instance stuck and not stopping in {}!'.format(pretty_time(time_)), logger.ERROR)

    def run(self) -> None:
        self._set_pool_size()
        while self.work:
            cmd, *item = self._queue.get()
            if cmd is None:
                break
            elif cmd == 'add':
                self._add_worker(*item)
            elif cmd == 'del':
                self._del_worker(*item)
            elif cmd == 'reload':
                self._reload()
            else:
                self.log('get cmd: {}. WTF?'.format(cmd), logger.CRIT)
        self._pool_size = 0
        self._remove_overloads()


def _make_dict_reply(cmd: str or None) -> dict:
    if cmd:
        return {'result': 'ok', 'id': cmd}
    else:
        return {'method': 'ping', 'params': [str(time.time())], 'id': 'pong'}


class DuplexInstance(API):
    def __init__(self, cfg, log, owner: Owner, name: str, conn: Connect, cmd: str or None, close_callback):
        super().__init__(cfg, log, owner, name=name)
        self._conn = conn
        self.__cmd = cmd
        self.__close_callback = close_callback
        self._notify_worker = SubscriptionsWorker(owner, conn)
        super().start()

    def close_signal(self):
        self.work = False
        self._notify_worker.close_signal()

    def join(self, timeout=10):
        self._notify_worker.join()
        super().join(timeout=timeout)

    @api_commands('subscribe', pure_json=True)
    def _api_subscribe(self, _, data: list):
        return self._notify_worker.subscribe(data)

    @api_commands('unsubscribe', pure_json=True)
    def _api_unsubscribe(self, _, data: list):
        return self._notify_worker.unsubscribe(data)

    def do_ws_allow(self, *args, **kwargs):
        return False

    def run(self):
        self._conn.settimeout(None)
        try:
            if self._testing():
                for line in self._conn.read():
                    if not self.work:
                        break
                    self.parse(line)
        finally:
            self._conn.close()
            self.log('close.', logger.INFO)
            self.__close_callback()

    def _testing(self) -> bool:
        reply = _make_dict_reply(self.__cmd)
        del self.__cmd
        try:
            self._conn.write(reply)
        except RuntimeError as e:
            self.log('OPEN ERROR: {}'.format(e), logger.ERROR)
            return False
        return True
