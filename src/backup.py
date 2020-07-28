import os
import threading
import time
import zipfile

import logger
import utils
from languages import F
from owner import Owner


class Backup(threading.Thread):
    NAME = 'backup'
    TIMESTAMP_FILE = 'timestamp'
    ALLOW_ONLY = ('settings', 'state', 'data', 'models')

    def __init__(self, cfg, log, owner: Owner):
        super().__init__(name=self.NAME.capitalize())
        self.cfg, self.log, self.own = cfg, log, owner

        self.work = False
        self._action = None
        self._sleep = threading.Event()
        self.root_paths = {
            target: os.path.relpath(cfg.path[target], cfg.path['home']) for target in self.ALLOW_ONLY
        }

    def start(self):
        self.work = True
        super().start()
        self.log('start', logger.INFO)

    def join(self, timeout=30):
        self._sleep.set()
        super().join(timeout=timeout)

    def reload(self):
        self._sleep.set()

    def manual_backup(self):
        self._action = 'backup'
        self._sleep.set()

    def _to_sleep(self):
        interval = self.cfg.gt('backup', 'interval')
        if interval <= 0:
            self._sleep.wait(3600)
            return 0
        interval *= 24 * 3600
        diff = time.time() - self._last_backup
        if diff >= interval:
            return 10
        if diff < 0:
            # Часы слетели. Что же делать?
            return 10 * 60
        return interval - diff

    def run(self):
        self._sleep.wait(12)
        self._verify_cfg()
        while self.work:
            to_sleep = self._to_sleep()
            self._sleep.wait(to_sleep)
            if not self.work:
                break
            if self._sleep.is_set():
                self._sleep.clear()
                if self._action == 'backup':
                    self._backup(manual=True, remove_old=False)
                self._action = None
            elif to_sleep:
                self._backup()

    def restore(self, filename: str):
        self.log(F('Запущено восстановление из бэкапа {}...', filename), logger.INFO)
        error, path = self._check_file(filename)
        if not path:
            self.log(F('Восстановление не возможно: {}', error), logger.CRIT)
            return
        fail_msg = F('Восстановление не удалось: {}')
        if not self._backup(remove_old=False):
            self.log(fail_msg.format(F('бэкап не создан')), logger.CRIT)
            return
        work_time = time.time()
        try:
            count = self._restore(path)
        except Exception as e:
            self.log(fail_msg.format(e), logger.CRIT)
        else:
            work_time = utils.pretty_time(time.time() - work_time)
            self.log(
                F('Восстановление завершено за {}, восстановлено {} файлов', work_time, count), logger.INFO)

    def _check_file(self, filename: str) -> tuple:
        if self.work:
            return F('Демон еще работает'), None
        if not utils.is_valid_base_filename(filename):
            return F('Некорректное имя файла: {}', repr(filename)), None
        path = os.path.join(self.cfg.path['backups'], filename)
        if not os.path.isfile(path):
            return F('Файл не найден: {}', path), None
        try:
            self._get_zip_timestamp(path)
        except Exception as e:
            return F('Архив поврежден: {}: {}', filename, e), None
        return None, path

    @property
    def _last_backup(self) -> float:
        return self.cfg.state[self.NAME]['last_backup']

    @_last_backup.setter
    def _last_backup(self, value: float):
        self.cfg.state[self.NAME]['last_backup'] = value

    def _verify_cfg(self):
        if self.NAME not in self.cfg.state:
            self.cfg.state[self.NAME] = {}
        self.cfg.state[self.NAME]['last_backup'] = self.cfg.state[self.NAME].get('last_backup', 0)

    def _backup(self, manual=False, remove_old=True) -> bool:
        def manual_notify(state: bool):
            if manual:
                self.own.sub_call('default', 'manual_backup', state)

        manual_notify(True)
        result = self.__backup(manual, remove_old)
        manual_notify(False)
        self.own.sub_call('default', self.NAME, 'ok' if result else 'error')
        return result

    def __backup(self, manual, remove_old) -> bool:
        def say(msg_: str):
            if manual:
                self.own.say(msg_, lvl=0)

        timestamp = time.time()
        if not manual:
            self._last_backup = timestamp
            self.cfg.save_state()
        filename = time.strftime('%Y.%m.%d-%H.%M.%S.zip', time.localtime(timestamp))
        file_path = os.path.join(self.cfg.path['backups'], filename)
        fail_msg = F('Ошибка создания бэкапа')
        if os.path.exists(file_path):
            self.log(F('Файл {} уже существует, отмена.', filename), logger.ERROR)
            say('{} - {}'.format(fail_msg, F('файл уже существует')))
            return False
        to_remove = self._candidates_to_remove() if remove_old else []
        work_time = time.time()
        try:
            old_size, new_size = self._make_backup(timestamp, file_path)
        except Exception as e:
            self.log('{} {}:{}'.format(fail_msg, filename, e), logger.ERROR)
            say(fail_msg)
            try:
                os.remove(file_path)
            except IOError:
                pass
            return False
        work_time = time.time() - work_time

        rate = round(new_size/old_size, 2)
        old_size = utils.pretty_size(old_size)
        new_size = utils.pretty_size(new_size)
        work_time = utils.pretty_time(work_time)
        msg = F('Бэкап {} создан за {} [size: {}, compressed: {}, rate: {}%]',
                filename, work_time, old_size, new_size, rate)
        self.log(msg, logger.INFO)
        say(F('Бэкап успешно создан'))
        if to_remove:
            self._remove_candidates([x for x, _ in to_remove])
        return True

    def _make_backup(self, timestamp: float, file_path: str):
        old_size, new_size = 0, 0

        def to_zip(path, zip_path_):
            if os.path.isfile(path):
                zf.write(path, zip_path_, zipfile.ZIP_DEFLATED)
            elif os.path.isdir(path):
                if zip_path_:
                    zf.write(path, zip_path_)
                for nm in sorted(os.listdir(path)):
                    to_zip(os.path.join(path, nm), os.path.join(zip_path_, nm))

        with zipfile.ZipFile(file_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for name, zip_path in self.root_paths.items():
                to_zip(self.cfg.path[name], zip_path)

            for file in zf.infolist():
                old_size += file.file_size
                new_size += file.compress_size

            zf.writestr(self.TIMESTAMP_FILE, str(timestamp).encode(), compress_type=zipfile.ZIP_DEFLATED)
            return old_size, new_size

    def _candidates_to_remove(self) -> list:
        max_count = self.cfg.gt('backup', 'max_count')
        if max_count < 1:
            return []
        result = self.backup_list(quiet=False)

        more = len(result) - max_count + 1
        if more < 1:
            return []
        return result[-more:]

    def _remove_candidates(self, files: list):
        for file in files:
            path = os.path.join(self.cfg.path['backups'], file)
            try:
                os.remove(path)
            except OSError as e:
                self.log(F('Ошибка удаления старого бэкапа {}: {}', file, e), logger.WARN)
            else:
                self.log(F('Удален старый бэкап {}', file))

    def backup_list(self, quiet=True) -> list:
        def log(msg, lvl=logger.DEBUG):
            if not quiet:
                self.log(msg, lvl)
        result = []
        for file in os.listdir(self.cfg.path['backups']):
            path = os.path.join(self.cfg.path['backups'], file)
            if not os.path.isfile(path):
                log('Is not a file: {}'.format(path))
            elif not path.endswith('.zip'):
                log('Is not a backup file: {}'.format(path))
            else:
                try:
                    result.append((file, self._get_zip_timestamp(path)))
                except Exception as e:
                    log('Archive corrupted (remove), {}: {}'.format(file, e), logger.WARN)
                    try:
                        os.remove(path)
                    except IOError:
                        pass
        result.sort(key=lambda x: x[1], reverse=True)
        return result

    def _get_zip_timestamp(self, file_path) -> float:
        with zipfile.ZipFile(file_path) as zf:
            bad_file = zf.testzip()
            if bad_file:
                raise RuntimeError('file corrupted: {}'.format(bad_file))
            return float(zf.read(self.TIMESTAMP_FILE).decode())

    def _restore(self, path: str):
        def check():
            allow = {self.cfg.path[x] for x in self.root_paths.keys()}
            for name_ in names:
                full_path_ = os.path.normpath(os.path.join(self.cfg.path['home'], name_))
                if not any(full_path_.startswith(test) for test in allow):
                    raise RuntimeError('Wrong, {} not in ({}). Terminated!'.format(
                        name_, ', '.join(self.root_paths.values()))
                    )

        count = 0
        with zipfile.ZipFile(path) as zf:
            names = [name for name in zf.namelist() if name != self.TIMESTAMP_FILE]
            check()
            for name in names:
                try:
                    restore = zf.extract(name, self.cfg.path['home'])
                except Exception as e:
                    raise RuntimeError('extracting {} error: {}'.format(repr(name), e))
                if os.path.isfile(restore):
                    self.log('Restore {}'.format(repr(os.path.relpath(restore, self.cfg.path['home']))))
                    count += 1
        return count
