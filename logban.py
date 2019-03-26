#!/usr/bin/python3

from getopt import getopt
import os
import os.path
import pyinotify
import re
import sys


class EventMaster(object):

    event_actions = {}    

    @staticmethod
    def register_action(event, action):
        try:
            EventMaster.event_actions[event].append(action)
        except KeyError:
            EventMaster.event_actions[event] = [action]

    @staticmethod
    def publish_event(event, **details):
        try:
            for action in EventMaster.event_actions[event]:
                action(event, **details)
        except KeyError:
            EventMaster.event_actions[event] = []


class FileMonitor(pyinotify.ProcessEvent):

    __notify_events = pyinotify.IN_CREATE | pyinotify.IN_DELETE | pyinotify.IN_MODIFY
    __wd_dict = {}
    __wm = pyinotify.WatchManager()

    logs = {}

    @staticmethod
    def register_log(path, position=0):
        if path not in FileMonitor.logs:
            FileMonitor.logs[path] = __MonitoredFile(path, position)
            directory = os.path.dirname(path)
            if directory not in FileMonitor.__wd_dict:
                FileMonitor.__wd_dict[directory] = \
                    FileMonitor.__wm.add_watch(directory, FileMonitor.__notify_events, rec=True)

    @staticmethod
    def loop():
        for log, watcher in FileMonitor.logs.items():
            lines = watcher.read_new_lines(auto_reset=False)
            if len(lines) > 0:
                EventMaster.publish_event(log, lines=lines)
        notifier = pyinotify.Notifier(FileMonitor.__wm, __INotifyEvent())
        notifier.loop()

    @staticmethod
    def close():
        for log in FileMonitor.logs:
            log.close()


class _FileMonitor__INotifyEvent(pyinotify.ProcessEvent):

    def process_IN_CREATE(self, event):
        if not event.dir and event.pathname in FileMonitor.logs:
            FileMonitor.logs[event.pathname].open()

    def process_IN_DELETE(self, event):
        if not event.dir and event.pathname in FileMonitor.logs:
            FileMonitor.logs[event.pathname].close()

    def process_IN_MODIFY(self, event):
        if not event.dir and event.pathname in FileMonitor.logs:
            lines = FileMonitor.logs[event.pathname].read_new_lines()
            if len(lines) > 0:
                EventMaster.publish_event(event.pathname, lines=lines)


class _FileMonitor__MonitoredFile(object):

    def __init__(self, file_path, position=0):
        self.file_path = file_path
        self.file = None
        self.open(position)

    def get_pos(self):
        return self.file.tell()

    def read_new_lines(self, auto_reset=True):
        if self.file == None:
            return []
        pos = self.get_pos()
        line = self.file.readline()
        if line == '' and auto_reset:
            self.reset()
            pos = self.file.tell()
            line = self.file.readline()
        lines = []
        while line != '':
            if line[-1:] == '\n':
                lines.append(line[:-1])
                pos = self.file.tell()
                line = self.file.readline()
            else:
                # if we get a partial line we seek back to the start of the line
                self.file.seek(pos)
                line = ''
        return lines

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


class LogFilter(object):
    
    def __init__(self, event, log_path, pattern):
        self.event = event
        self.pattern = re.compile(pattern)
        self.log_path = log_path

    def filter_line(self, log, lines, ** named_params):
        for line in lines:
            found = self.pattern.search(line)
            if found is not None:
                EventMaster.publish_event(self.event,
                                          log=self.log_path,
                                          lines=[line],
                                          addresses=found.group('host'),
                                          user=found.group('user'))

class Configuration(object):

    @staticmethod
    def load_config():
        opt_list, _ = getopt(sys.argv[1:], '', ['config='])
        opt_list = { option[2:]: value for option, value in opt_list }
        return Configuration.load_config_files(**opt_list)

    @staticmethod
    def load_config_files(config='/etc/logban', **other_options):
        filters_conf = Configuration.load_filter_files(config)
        for filter_conf in filters_conf:
            log_path = os.path.abspath(filter_conf['log_path'])
            # Enable monitoring of this log
            FileMonitor.register_log(log_path)
            # Add a new filter for this log
            filter = LogFilter(**filter_conf)
            EventMaster.register_action(log_path, filter.filter_line)

    @staticmethod
    def load_filter_files(config):
        filter_re = re.compile(r'^ *(?P<log_path>[^#|]+) *\| *(?P<event>[^ |]+) *\|(?P<pattern>.+) *$')
        config = os.path.join(config, 'filters')
        filters = []
        filter_files = os.listdir(config)
        for filter_path in filter_files:
            filter_path = os.path.join(config, filter_path)
            if filter_path.endswith('.conf'):
                with open(filter_path) as filter_file:
                    for line in filter_file:
                        match = filter_re.match(line)
                        if match is not None:
                            filter = {
                                    'log_path': match.group('log_path'),
                                    'event': match.group('event'),
                                    'pattern': match.group('pattern').format(
                                        host=r'(?P<host>[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)',
                                        user=r'(?P<user>.*)'
                                    )
                                }
                            filters.append(filter)
        return filters


Configuration.load_config()
EventMaster.register_action('test_log', lambda event, ** args: print("Triggered: %s: %s" % (event, args)))
FileMonitor.loop()
