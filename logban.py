#! /usr/bin/python3

from configobj import ConfigObj
from datetime import datetime, timedelta
from getopt import getopt
import json
import os
import os.path
import pyinotify
import re
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
        actions = event_actions[event]
    except KeyError:
        # Avoid excessive exceptions, If an event is published then assume it will be again and create an event
        # even if there are no listeners
        actions = []
        event_actions[event] = actions
    for action in actions:
        action(event, **details)



#############################
# File monitoring (inotify) #
#############################

__notify_events = pyinotify.IN_CREATE | pyinotify.IN_DELETE | pyinotify.IN_MODIFY
__wd_dict = {}
__wm = pyinotify.WatchManager()

file_monitors = {}


def register_file(path):
    if path not in file_monitors:
        file_monitors[path] = FileMonitor(path)
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

    def __init__(self, file_path):
        self.file_path = file_path
        self.file = None
        self.filters = []
        with DBSession() as session:
            self.status_entry = session.query(DBLogStatus).get(file_path)
            if self.status_entry is None:
                self.status_entry = DBLogStatus(path=file_path, position=0)
                session.add(self.status_entry)
                session.commit()
        self.open(self.status_entry.position)

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
                with DBSession() as session:
                    for line_filter in self.filters:
                        line_filter.filter_line(log=self.file_path, line=line[:-1])
                    pos = self.file.tell()
                    line = self.file.readline()
                    self.status_entry.position = pos
                    session.add(self.status_entry)
                    session.commit()
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

    def filter_line(self, line, ** named_params):
        found = self.pattern.search(line)
        if found is not None:
            params = found.groupdict()
            for processor in param_processors:
                processor(params)
            publish_event(self.event, log_path=self.log_path, lines=[line], **params)


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


###########
# Trigger #
###########

class GroupCounterTrigger(object):

    def __init__(self, trigger_id, group_on, result_event,
               trigger_events=[], reset_events=[], count=5, timeout='2592000', **ignored_params):
        trigger_events = _wrap_cofig_list(trigger_events)
        reset_events = _wrap_cofig_list(reset_events)
        self.group_on = _wrap_cofig_list(group_on)
        self.trigger_id = trigger_id
        self.result_event = result_event
        self.events = {event: True for event in trigger_events}
        self.events.update({event: False for event in reset_events})
        self.count = int(count)
        self.timeout = timedelta(seconds=int(timeout))

    def process_event(self, event_name, lines, **params):
        relavent_params = {key: params[key] for key in self.group_on}
        trigger_key = json.dumps(relavent_params, sort_keys=True)
        if self.events[event_name]:
            time = params.get('time', datetime.now())
            with DBSession() as session:
                status = session.query(DBTriggerStatus).get((self.trigger_id, trigger_key))
                if status is None:
                    status = DBTriggerStatus(
                        trigger_id=self.trigger_id,
                        status_key=trigger_key,
                        times_triggered=1,
                        last_triggered=time,
                        first_triggered=time
                    )
                else:
                    status.last_triggered = time
                    status.times_triggered += 1
                for line in lines:
                    status.lines.append(DBTriggerStatusLine(triggered_time=time, triggered_line=line))
                status.times.append(DBTriggerStatusTime(time_triggered=time))
                if status.times_triggered >= self.count:
                    for time in status.times:
                        if time.time_triggered < status.last_triggered - self.timeout:
                            status.times.remove(time)
                            status.times_triggered -= 1
                    if status.times_triggered >= self.count:
                        publish_event(
                            self.result_event,
                            lines=[line.triggered_line for line in status.lines],
                            time=time,
                            **relavent_params
                        )
                session.add(status)
                session.commit()
        else:
            # reset
            pass


#################
# Configuration #
#################

config_trigger_types = {
    'group_counter': GroupCounterTrigger
}


def load_config():
    opt_list, _ = getopt(sys.argv[1:], '', ['config-path='])
    opt_list = {option[2:].replace('-','_'): value for option, value in opt_list}
    return load_config_files(**opt_list)


def load_config_files(config_path='/etc/logban'):
    global db_engine
    # Load core config
    core_config = ConfigObj(os.path.join(config_path, 'logban.conf'))
    filter_config = load_config_filters(config_path)
    trigger_config = load_config_triggers(config_path)
    execute_config(
        core_config=core_config,
        filter_config=filter_config,
        trigger_config=trigger_config,
        action_config=None
    )


def load_config_filters(config):
    filter_re = re.compile(r'^ *(?P<log_path>[^#|]*[^#| ]+) *\| *(?P<event>[^ |]+) *\| *(?P<pattern>.+) *$')
    config = os.path.join(config, 'filters')
    filters = {}
    for filter_path in os.listdir(config):
        filter_path = os.path.join(config, filter_path)
        if filter_path.endswith('.conf'):
            with open(filter_path) as filter_file:
                for line in filter_file:
                    match = filter_re.match(line)
                    if match is not None:
                        params = match.groupdict()
                        if params['log_path'] not in filters:
                            filters[params['log_path']] = [params]
                        else:
                            filters[params['log_path']].append(params)
    return filters


def load_config_triggers(config, triggers={}):
    config = os.path.join(config, 'triggers')
    for trigger_path in os.listdir(config):
        trigger_path = os.path.join(config, trigger_path)
        if trigger_path.endswith('.conf'):
            new_triggers = ConfigObj(trigger_path)
            for name, params in new_triggers.items():
                if name in triggers:
                    triggers[name].update(params)
                else:
                    triggers[name] = params
    return triggers


def execute_config(core_config, filter_config, trigger_config, action_config):
    global file_monitors
    # Open database connection
    DBSession.initialize_db(**core_config.get('db', default={}))

    # Setup file monitors and filters
    for file_path, filter_conf in filter_config.items():
        file_path = os.path.abspath(file_path)
        if file_path not in file_monitors:
            register_file(file_path)
        for config in filter_conf:
            new_filter = LogFilter(**config)
            file_monitors[file_path].filters.append(new_filter)

    # Setup triggers
    for trigger_name, config in trigger_config.items():
        trigger_type = config_trigger_types[config['type']]
        new_trigger = trigger_type(trigger_name, **config)
        for event, _ in new_trigger.events.items():
            register_action(event, new_trigger.process_event)


def _wrap_cofig_list(value):
    if isinstance(value, list):
        return value
    if value == '':
        return []
    return [value]


############
# Database #
############

DBBase = sqlalchemy.ext.declarative.declarative_base()


# This class only works if single threaded!  Forks must not happen with open sessions and pthreads are completely out
class DBSession:

    __db_engine = None
    _db_session = None
    __open_new_session = None
    __ref_count = 0

    def __init__(self):
        self.is_commit = False

    def __enter__(self):
        if DBSession.__ref_count == 0:
            DBSession._db_session = DBSession.__open_new_session()
        DBSession.__ref_count += 1
        DBSession._db_session.begin_nested()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_commit:
            DBSession._db_session.commit()
        else:
            DBSession._db_session.rollback()
        DBSession.__ref_count -= 1
        if DBSession.__ref_count == 0:
            DBSession._db_session.close()
            DBSession._db_session = None

    def __getattr__(self, name):
        return getattr(DBSession._db_session, name)

    def commit(self):
        self.is_commit = True

    def rollback(self):
        self.is_commit = False

    @staticmethod
    def initialize_db(path='/var/lib/logban/logban.sqlite3', **excess_args):
        global DBBase
        DBSession.__db_engine = sqlalchemy.create_engine('sqlite:///%s' % path, echo=True)
        DBBase.metadata.create_all(DBSession.__db_engine)
        DBSession.__open_new_session = sqlalchemy.orm.sessionmaker(bind=DBSession.__db_engine)


class DBTriggerStatus(DBBase):

    __tablename__ = 'trigger_status'

    trigger_id = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    status_key = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    times_triggered = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    last_triggered = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    first_triggered = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    lines = sqlalchemy.orm.relationship('DBTriggerStatusLine')
    times = sqlalchemy.orm.relationship('DBTriggerStatusTime')

    def __repr__(self):
        return "<DBTriggerStatus(trigger_id='%s', status_key='%s', times_triggered='%d',"\
               "last_triggered='%s', first_triggered='%s')>" % (
                self.trigger_id,
                self.status_key,
                self.times_triggered,
                self.last_triggered,
                self.first_triggered)


class DBTriggerStatusTime(DBBase):

    __tablename__ = 'trigger_times'

    id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.Sequence('trigger_time_seq'), primary_key=True)
    trigger_id = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    status_key = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    time_triggered = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    __table_args__  = (sqlalchemy.ForeignKeyConstraint(['trigger_id', 'status_key'],
                                                      ['trigger_status.trigger_id', 'trigger_status.status_key'],
                                                      ondelete="CASCADE"),{})

    def __repr__(self):
        return "<DBTriggerStatusTime(trigger_id='%s', status_key='%s', time_triggered='%s')>" % (
                self.trigger_id,
                self.status_key,
                self.time_triggered)


class DBTriggerStatusLine(DBBase):

    __tablename__ = 'trigger_lines'

    id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.Sequence('trigger_line_seq'), primary_key=True)
    trigger_id = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    status_key = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    triggered_time = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    triggered_line = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    __table_args__  = (sqlalchemy.ForeignKeyConstraint(['trigger_id', 'status_key'],
                                                      ['trigger_status.trigger_id', 'trigger_status.status_key'],
                                                      ondelete="CASCADE"),{})

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


def main():
    load_config()
    loop()


if __name__ == '__main__':
    main()
