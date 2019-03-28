#! /usr/bin/python3

from configobj import ConfigObj
from datetime import datetime, timedelta
from getopt import getopt
import json
import os
import os.path
import pyinotify
import re
import signal
import sys
import sqlalchemy
import sqlalchemy.ext.declarative
import sqlalchemy.orm


##########
# Events #
##########

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


#############################
# File monitoring (inotify) #
#############################

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


def save_file_positions():
    session = db_session()
    for path, monitor in file_monitors.items():
        session.merge(DBLogStatus(path=path, position=monitor.get_pos()))
    session.commit()
    session.close()


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
            self.open()
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


##################
# Line Filtering #
##################

class LogFilter(object):

    friendly_params = {
        'rhost': r'(?P<rhost>[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)',
        'port': r'(?P<port>[0-9]{1,5})',
        'user': r'(?P<user>.*)',
        'session': r'(?P<session>.*)',
        'friendly_time':
            r'(?P<friendly_time>(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
            ' [0-9]{1,2} [0-9]{2}:[0-9]{2}:[0-9]{2})'
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


#################
# Configuration #
#################

def load_config():
    opt_list, _ = getopt(sys.argv[1:], '', ['config-path='])
    opt_list = {option[2:].replace('-','_'): value for option, value in opt_list}
    return load_config_files(**opt_list)


def load_config_files(config_path='/etc/logban'):
    global db_engine
    # Load core config
    core_config =  ConfigObj(os.path.join(config_path, 'logban.conf'))
    filters_conf = load_config_filters(config_path)

    # Open database connection
    connect_db(**core_config.get('db', default={}))

    # Setup file monitors and filters
    session = db_session()
    log_status = {status.path: status.position for status in session.query(DBLogStatus)}
    session.close()
    for filter_conf in filters_conf:
        log_path = os.path.abspath(filter_conf['log_path'])
        # Enable monitoring of this log, don't worry about duplication
        register_file(log_path, log_status.get(log_path,0))
        # Add a new filter for this log
        log_filter = LogFilter(**filter_conf)
        register_action(log_path, log_filter.filter_line)


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


############
# Database #
############

db_engine = None
db_session = None

DBBase = sqlalchemy.ext.declarative.declarative_base()


def connect_db(path='/var/lib/logban/logban.sqlite3', **excess_args):
    global DBBase, db_engine, db_session
    db_engine = sqlalchemy.create_engine('sqlite:///%s' % path, echo=True)
    DBBase.metadata.create_all(db_engine)
    db_session = sqlalchemy.orm.sessionmaker(bind=db_engine)


class DBTriggerStatus(DBBase):
    __tablename__ = 'trigger_status'

    trigger_id = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    status_key = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    times_triggered = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    last_triggered = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    first_triggered = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)

    def __repr__(self):
        return "<DBTriggerStatus(trigger_id='%s', status_key='%s', times_triggered='%d',"\
               "last_triggered='%s', first_triggered='%s')>" % (
                self.trigger_id,
                self.status_key,
                self.times_triggered,
                self.last_triggered,
                self.first_triggered)


class DBTriggerStatusTime(DBBase):
    __tablename__ = 'trigger_status_times'

    trigger_id = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    status_key = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    time_triggered = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    def __repr__(self):
        return "<DBTriggerStatusTime(trigger_id='%s', status_key='%s', time_triggered='%s')>" % (
                self.trigger_id,
                self.status_key,
                self.time_triggered)


class DBTriggerStatusLine(DBBase):
    __tablename__ = 'trigger_status_lines'

    trigger_id = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    status_key = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    triggered_time = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    triggered_line = sqlalchemy.Column(sqlalchemy.String, nullable=False)

    def __repr__(self):
        return "<DBTriggerStatusLine(trigger_id='%s', status_key='%s', triggered_time='%d', triggered_line='%s')>" % (
                self.trigger_id,
                self.status_key,
                self.triggered_time,
                self.triggered_line)


class DBLogStatus(DBBase):
    __tablename__ = 'log_status'

    path = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    position = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    def __repr__(self):
        return "<DBLogStatus(path='%s', position='%d', triggered_time='%d', triggered_line='%s')>" % (
                self.path,
                self.position)


########################
# Startup and shutdown #
########################

def __on_sigterm(signum, frame):
    save_file_positions()
    exit(0)


def main():
    signal.signal(signal.SIGINT, __on_sigterm)
    signal.signal(signal.SIGTERM, __on_sigterm)
    load_config()
    register_action('sshd_auth_success', lambda event, ** args: print("Triggered: %s: %s" % (event, args)))
    loop()


if __name__ == '__main__':
    main()
