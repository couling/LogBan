#!/usr/bin/python3

from datetime import datetime, date, timedelta
from getopt import getopt
import os
import os.path
import pyinotify
import re
import sys


event_actions = {}


def register_action(event, action):
    try:
        event_actions[event].append(action)
    except KeyError:
        event_actions[event] = [action]


def publish_event(event, **details):
    try:
        for action in event_actions[event]:
            action(event, **details)
    except KeyError:
        # Avoid excessive exceptions, If an event is published then assume it will be again and create an event
        # even if there are no listeners
        event_actions[event] = []


__notify_events = pyinotify.IN_CREATE | pyinotify.IN_DELETE | pyinotify.IN_MODIFY
__wd_dict = {}
__wm = pyinotify.WatchManager()

file_monitors = {}


def register_file(path, position=0):
    if path not in file_monitors:
        file_monitors[path] = FileMonitor(path, position)
        directory = os.path.dirname(path)
        if directory not in __wd_dict:
            __wd_dict[directory] = __wm.add_watch(directory, __notify_events, rec=True)


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
            __wm.remove_watch(__wd_dict[directory])


def loop():
    for log, watcher in file_monitors.items():
        watcher.read_new_lines(auto_reset=False)
    notifier = pyinotify.Notifier(__wm, __INotifyEvent())
    notifier.loop()


def close_monitors():
    for log, monitor in file_monitors.items():
        monitor.close()


class __INotifyEvent(pyinotify.ProcessEvent):

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

    def __init__(self, file_path, position=0):
        self.file_path = file_path
        self.file = None
        self.open(position)

    def get_pos(self):
        return self.file.tell()

    def read_new_lines(self, auto_reset=True):
        if self.file is None:
            return
        pos = self.get_pos()
        line = self.file.readline()
        if line == '' and auto_reset:
            self.reset()
            pos = self.file.tell()
            line = self.file.readline()
        while line != '':
            if line[-1:] == '\n':
                publish_event(self.file_path, line=line[:-1])
                pos = self.file.tell()
                line = self.file.readline()
            else:
                # if we get a partial line we seek back to the start of the line
                self.file.seek(pos)
                line = ''

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

    friendly_params = {
        'rhost': r'(?P<rhost>[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)',
        'port': r'(?P<port>[0-9]{1,5})',
        'user': r'(?P<user>.*)',
        'session': r'(?P<session>.*)',
        'friendly_time': r'(?P<friendly_time>(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [0-9]{1,2} [0-9]{2}:[0-9]{2}:[0-9]{2})'
    }
    
    def __init__(self, event, log_path, pattern):
        self.event = event
        self.source_pattern = pattern
        self.pattern = re.compile(pattern)
        self.log_path = log_path
        self.pattern = re.compile(pattern.format(**LogFilter.friendly_params))

    def filter_line(self, log, line, ** named_params):
        found = self.pattern.search(line)
        if found is not None:
            params = found.groupdict()
            for processor in param_processors:
                processor(params)
            publish_event(self.event, log_path=self.log_path, logs=log, lines=[line], **params)


def _process_friendly_time(params):
    if 'friendly_time' in params:
        log_time = datetime.strptime(params['friendly_time'], '%b %d %H:%M:%S')
        today = datetime.now()
        guess_year = log_time.replace(year=today.year)
        if guess_year > today + timedelta(days=1):
            guess_year = log_time.replace(year=today.year - 1)
        params['time'] = guess_year
        del params['friendly_time']


param_processors = [
    _process_friendly_time
]


def load_config():
    opt_list, _ = getopt(sys.argv[1:], '', ['config='])
    opt_list = { option[2:]: value for option, value in opt_list }
    return load_config_files(**opt_list)


def load_config_files(config='/etc/logban', **other_options):
    filters_conf = load_config_filters(config)
    for filter_conf in filters_conf:
        log_path = os.path.abspath(filter_conf['log_path'])
        # Enable monitoring of this log
        register_file(log_path)
        # Add a new filter for this log
        filter = LogFilter(**filter_conf)
        register_action(log_path, filter.filter_line)


def load_config_filters(config):
    filter_re = re.compile(r'^ *(?P<log_path>[^#|]*[^#| ]+) *\| *(?P<event>[^ |]+) *\| *(?P<pattern>.+) *$')
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
                        filters.append(match.groupdict())
    return filters


load_config()
register_action('sshd_auth_success', lambda event, ** args: print("Triggered: %s: %s" % (event, args)))
loop()
