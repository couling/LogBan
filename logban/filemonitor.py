import os.path
import pyinotify
import sqlalchemy
import logging
import threading

from logban.core import DBBase, DBSession, main_loop, main_loop_future


_logger = logging.getLogger(__name__)

_notify_events = pyinotify.IN_CREATE | pyinotify.IN_DELETE | pyinotify.IN_MODIFY
_wd_dict = {}
_wm = pyinotify.WatchManager()

_loop_scheduled = False

file_monitors = {}


def register_file(path):
    global _loop_scheduled
    if path not in file_monitors:
        new_monitor = FileMonitor(path)
        file_monitors[path] = new_monitor
        directory = os.path.dirname(path)
        if directory not in _wd_dict:
            _wd_dict[directory] = _wm.add_watch(directory, _notify_events, rec=True)
        if not _loop_scheduled:
            _loop_scheduled=True
            main_loop.call_soon(_file_monitor_loop)


def unregister_file(path):
    if path in file_monitors:
        file_monitor = file_monitors[path]
        del file_monitors[path]
        file_monitor.close()
        directory = os.path.dirname(path)
        # Check for other file monitors in the same directory before removing the directory
        for other_path, _ in file_monitors:
            if os.path.dirname(other_path) == directory:
                break
        else:
            _wm.del_watch(_wd_dict[directory])


def _file_monitor_loop():
    _logger.info("Starting File Monitors")
    for log, watcher in file_monitors.items():
        _logger.info("Initializing %s", watcher.file_path)
        watcher.read_new_lines()
    notifier = pyinotify.Notifier(_wm, _INotifyEvent())
    thread = threading.Thread(target=notifier.loop)
    thread.setDaemon(True)
    thread.start()
    main_loop_future.add_done_callback(_shutdown)


def _shutdown(*_):
    close_monitors()


def close_monitors():
    for log, monitor in file_monitors.items():
        monitor.close()


class _INotifyEvent(pyinotify.ProcessEvent):

    def process_IN_CREATE(self, event):
        if not event.dir and event.pathname in file_monitors:
            main_loop.call_soon_threadsafe(file_monitors[event.pathname].open)

    def process_IN_DELETE(self, event):
        if not event.dir and event.pathname in file_monitors:
            main_loop.call_soon_threadsafe(file_monitors[event.pathname].close)

    def process_IN_MODIFY(self, event):
        if not event.dir and event.pathname in file_monitors:
            main_loop.call_soon_threadsafe(file_monitors[event.pathname].read_new_lines)


class FileMonitor(object):

    def __init__(self, file_path):
        self.file_path = file_path
        self.file = None
        self.filters = []
        with DBSession() as session:
            status_entry = session.query(_DBLogStatus).get(file_path)
            if status_entry is None:
                status_entry = _DBLogStatus(path=file_path, position=0)
                session.add(status_entry)
                position = 0
            else:
                position = status_entry.position
            self.status_entry = status_entry
        self.open(position)

    def read_new_lines(self):
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

    def open(self, position=0):
        self.close()
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

    def close(self):
        if self.file is not None:
            _logger.info("Closing %s", self.file_path)
            self.file.close()
            self.file = None


class _DBLogStatus(DBBase):

    __tablename__ = 'log_status'

    path = sqlalchemy.Column(sqlalchemy.String(1000), primary_key=True)
    position = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
