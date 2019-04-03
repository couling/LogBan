import os.path
import pyinotify
import sqlalchemy

from logban.core import DBBase, DBSession


_notify_events = pyinotify.IN_CREATE | pyinotify.IN_DELETE | pyinotify.IN_MODIFY
_wd_dict = {}
_wm = pyinotify.WatchManager()

file_monitors = {}


def register_file(path):
    if path not in file_monitors:
        file_monitors[path] = FileMonitor(path)
        directory = os.path.dirname(path)
        if directory not in _wd_dict:
            _wd_dict[directory] = _wm.add_watch(directory, _notify_events, rec=True)


def unregister_file(path):
    if path in file_monitors:
        file_moitor = file_monitors[path]
        del file_monitors[path]
        file_moitor.close()
        directory = os.path.dirname(path)
        # Check for other file monitors in the same directory before removing the directory
        for other_path, _ in file_monitors:
            if os.path.dirname(other_path) == directory:
                break
        else:
            _wm.del_watch(_wd_dict[directory])


def file_monitor_loop():
    for log, watcher in file_monitors.items():
        watcher.read_new_lines(auto_reset=False)
    notifier = pyinotify.Notifier(_wm, _INotifyEvent())
    notifier.loop()


def close_monitors():
    for log, monitor in file_monitors.items():
        monitor.close()


class _INotifyEvent(pyinotify.ProcessEvent):

    def process_IN_CREATE(self, event):
        if not event.dir and event.pathname in file_monitors:
            file_monitors[event.pathname].open()

    def process_IN_DELETE(self, event):
        if not event.dir and event.pathname in file_monitors:
            file_monitors[event.pathname].close()

    def process_IN_MODIFY(self, event):
        if not event.dir and event.pathname in file_monitors:
            file_monitors[event.pathname].read_new_lines()


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
                session.commit()
                position = 0
            else:
                position = status_entry.position
            self.status_entry = status_entry
        self.open(position)

    def get_pos(self):
        return self.file.tell()

    def read_new_lines(self, auto_reset=True):
        if self.file is None:
            return
        pos = self.get_pos()
        with DBSession() as session:
            line = self.file.readline()
            if line == '' and auto_reset:
                self.open()
                pos = self.file.tell()
                line = self.file.readline()
            while line != '':
                if line[-1:] == '\n':
                    for line_filter in self.filters:
                        line_filter.filter_line(line=(line[:-1]))
                    pos = self.file.tell()
                    line = self.file.readline()
                else:
                    # if we get a partial line we seek back to the start of the line
                    self.file.seek(pos)
                    line = ''
            self.status_entry.position = pos
            session.add(self.status_entry)
            session.commit()

    def open(self, position=0):
        self.close()
        if os.path.isfile(self.file_path):
            self.file = open(self.file_path, 'r')
            if position != 0:
                self.file.seek(position, 0)

    def close(self):
        if self.file is not None:
            self.file.close()
            self.file = None


class _DBLogStatus(DBBase):

    __tablename__ = 'log_status'

    path = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    position = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
