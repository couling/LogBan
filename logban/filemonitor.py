import os.path
import pyinotify
import sqlalchemy
import logging
import threading

from logban.core import DBBase, DBSession, main_loop, main_loop_future
from abc import ABC, abstractmethod

_logger = logging.getLogger(__name__)

all_file_monitors = {}


class AbstractFileMonitor(ABC):

    def __init__(self):
        self.filters = []

    @abstractmethod
    def shutdown(self):
        pass


class FileMonitor(AbstractFileMonitor):

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.file = None
        self.directory_monitor = _DirectoryMonitor.get_directory_monitor_for(file_path)
        self.directory_monitor.file_monitors[file_path] = self
        with DBSession() as session:
            status_entry = session.query(_DBLogStatus).get(file_path)
            if status_entry is None:
                status_entry = _DBLogStatus(path=file_path, position=0)
                session.add(status_entry)
                position = 0
            else:
                position = status_entry.position
            self.status_entry = status_entry
        self._open(position)

    def shutdown(self):
        del self.directory_monitor.file_monitors[self.file_path]
        self._close()
        # Last one out turn off the lights
        if len(self.directory_monitor.file_monitors) == 0:
            self.directory_monitor.shutdown()

    def _read_new_lines(self):
        if self.file is None:
            return
        pos = self.file.tell()
        line = self.file.readline()
        if line == '':
            self.file.seek(0, os.SEEK_END)
            new_pos = self.file.tell()
            if pos < new_pos:
                _logger.info("Resetting %s to position 0", self.file_path)
                self.file.seek(0, os.SEEK_SET)
                pos = self.file.tell()
                line = self.file.readline()
            elif pos > new_pos:
                # file extended while checking
                self.file.seek(pos, os.SEEK_SET)
        while line != '':
            if line[-1:] == '\n':
                for line_filter in self.filters:
                    line_filter.filter_line(line=(line[:-1]))
                pos = self.file.tell()
                line = self.file.readline()
            else:
                # if we get a partial line we seek back to the start of the line
                self.file.seek(pos, os.SEEK_SET)
                line = ''
        with DBSession() as session:
            self.status_entry.position = pos
            session.merge(self.status_entry)

    def _open(self, position=0):
        self._close()
        if os.path.isfile(self.file_path):
            _logger.info("Opening %s at position %d", self.file_path, position)
            self.file = open(self.file_path, 'r')
            if position != 0:
                self.file.seek(0, os.SEEK_END)
                if self.file.tell() < position:
                    _logger.info("Resetting %s to position 0", self.file_path)
                    self.file.seek(0, os.SEEK_SET)
                else:
                    self.file.seek(position, os.SEEK_SET)
        else:
            _logger.warning("File does not exist %s", self.file_path)

    def _close(self):
        if self.file is not None:
            _logger.info("Closing %s", self.file_path)
            self.file.close()
            self.file = None


class _DirectoryMonitor(pyinotify.ProcessEvent):

    NOTIFY_EVENTS = pyinotify.IN_CREATE | pyinotify.IN_DELETE | pyinotify.IN_MODIFY

    all_directory_monitors = {}

    watch_manager = None

    def __init__(self, path):
        self.file_monitors = {}
        self.path = path
        if _DirectoryMonitor.watch_manager is None:
            _DirectoryMonitor.watch_manager = pyinotify.WatchManager()
            # We don't start a thread now, we register a callback to run one later
            main_loop.call_soon(_DirectoryMonitor.directory_monitor_loop)
        self.watch_handle = _DirectoryMonitor.watch_manager.add_watch(path, _DirectoryMonitor.NOTIFY_EVENTS, self)[path]

    def shutdown(self):
        _DirectoryMonitor.watch_manager.del_watch(self.watch_handle)

    def process_IN_CREATE(self, event):
        if not event.dir and event.pathname in self.file_monitors:
            main_loop.call_soon_threadsafe(self.file_monitors[event.pathname]._open)

    def process_IN_DELETE(self, event):
        if not event.dir and event.pathname in self.file_monitors:
            main_loop.call_soon_threadsafe(self.file_monitors[event.pathname]._close)

    def process_IN_MODIFY(self, event):
        if not event.dir and event.pathname in self.file_monitors:
            main_loop.call_soon_threadsafe(self.file_monitors[event.pathname]._read_new_lines)

    @staticmethod
    def get_directory_monitor_for(path):
        directory = os.path.dirname(path)
        try:
            return _DirectoryMonitor.all_directory_monitors[directory]
        except KeyError:
            new_monitor = _DirectoryMonitor(directory)
            _DirectoryMonitor.all_directory_monitors[directory] = new_monitor
            return new_monitor

    @staticmethod
    def directory_monitor_loop():
        _logger.info("Starting File Monitors")
        for directory, directory_monitor in _DirectoryMonitor.all_directory_monitors.items():
            for file_path, file_monitor in directory_monitor.file_monitors.items():
                _logger.info("Initializing %s", file_path)
                file_monitor._read_new_lines()
        notifier = pyinotify.Notifier(_DirectoryMonitor.watch_manager)
        thread = threading.Thread(target=notifier.loop)
        thread.setDaemon(True)
        thread.start()
        main_loop_future.add_done_callback(lambda _: _DirectoryMonitor.close_monitors())

    @staticmethod
    def close_monitors():
        to_shutdown = []
        for directory, directory_monitor in _DirectoryMonitor.all_directory_monitors.items():
            for file_path, file_monitor in directory_monitor.file_monitors.items():
                to_shutdown.append(file_monitor)
        for file_monitor in to_shutdown:
            file_monitor.shutdown()


class _DBLogStatus(DBBase):

    __tablename__ = 'log_status'

    path = sqlalchemy.Column(sqlalchemy.String(1000), primary_key=True)
    position = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
