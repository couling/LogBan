#!/usr/bin/python3

import os.path
import pyinotify


class EventMaster(object):

    event_actions = {}    

    @staticmethod
    def register_action(event, action):
        try:
            EventMaster.event_actions[event].append(action)
        except KeyError:
            EventMaster.event_actions[event] = [action]

    def publish_event(event, **details):
        try:
            for action in EventMaster.event_actions[event]:
                action(event, **details)
        except KeyError:
            EventMaster.event_actions[event] = []


class FileMonitor(pyinotify.ProcessEvent):

    def __init__(self):
        self.logs = {}
        self._wm = pyinotify.WatchManager()
        self._notifier = pyinotify.Notifier(self._wm, self)
        self._wd_dict = {}

    def process_IN_CREATE(self, event):
        if not event.dir and event.pathname in self.logs:
            self.logs[event.pathname].reset()

    def process_IN_DELETE(self, event):
        if not event.dir and event.pathname in self.logs:
            self.logs[event.pathname].close()

    def process_IN_MODIFY(self, event):
        if not event.dir and event.pathname in self.logs:
            self.logs[event.pathname].notify_change()

    #def process_default(self,event):
    #    print(event)

    def register_log(self, path, position=0):
        path = os.path.realpath(path)
        if path not in self.logs:
            self.logs[path] = _MonitoredFile(path, position)
            directory = os.path.dirname(path)
            if directory not in self._wd_dict:
                self._wd_dict[directory] = self._wm.add_watch(directory,
                        pyinotify.IN_CREATE | pyinotify.IN_DELETE | pyinotify.IN_MODIFY,
                        rec=True)

    def loop(self):
        for log, watcher in self.logs.items():
            watcher.notify_change()
        self._notifier.loop()



class _MonitoredFile(object):

    def __init__(self, log_file, position=0):
        self.log_file = log_file
        self.open_file = None
        self._open_file()

    def reset(self):
        self.close()
        self._open_file()

    def notify_change(self):
        pos = self.open_file.tell()
        line = self.open_file.readline()
        if line == '':
            self.reset()
            pos = self.open_file.tell()
            line = self.open_file.readline()
        while line != '':
            if line[-1:] == '\n':
                EventMaster.publish_event(self.log_file, line=line[:-1])
                pos = self.open_file.tell()
                line = self.open_file.readline()
            else:
                print("Self reset %s" % self.log_file)
                # if we get a partial line we seek back to the start of the line
                self.open_file.seek(pos)
                line = ''

    def _open_file(self):
        if os.path.isfile(self.log_file):
            self.open_file = open(self.log_file, 'r')

    def close(self):
        if self.open_file is not None:
            self.open_file.close()
            self.open_file = None



class LogFilter(object):
    
    def __init__(self, event, pattern):
        global event_actions
        self.event = event
        self.pattern = pattern.compile()

    def filter_line(log, line):
        found = self.pattern.search(line)
        if found is not None:
            EventMaster.publish_event(event, lines=[line], address=found.group('host'), user=found('user'))





file_monitor = FileMonitor()
file_monitor.loop()


