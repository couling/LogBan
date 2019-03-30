import re

from datetime import datetime, timedelta

from logban.core import publish_event


##################
# Line Filtering #
##################

class LogFilter(object):

    def __init__(self, event, log_path, pattern):
        self.event = event
        self.source_pattern = pattern
        self.pattern = re.compile(pattern)
        self.log_path = log_path
        self.pattern = re.compile(pattern.format(**named_groups))

    def filter_line(self, line):
        found = self.pattern.search(line)
        if found is not None:
            params = found.groupdict()
            for processor in param_processors:
                processor(params)
            publish_event(self.event, log_path=self.log_path, lines=[line], **params)


def _process_syslog_time(params):
    if 'syslog_time' in params:
        log_time = datetime.strptime(params['syslog_time'], '%b %d %H:%M:%S')
        today = datetime.now()
        guess_year = log_time.replace(year=today.year)
        if guess_year > today + timedelta(days=1):
            guess_year = log_time.replace(year=today.year - 1)
        params['time'] = guess_year
        del params['syslog_time']


named_groups = {
    'rhost': r'(?P<rhost>[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)',
    'lhost': r'(?P<lhost>[^ ]+)',
    'port': r'(?P<port>[0-9]{1,5})',
    'user': r'(?P<user>.*)',
    'session': r'(?P<session>.*)',
    'syslog_time':
        r'(?P<syslog_time>(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
        ' {1,2}[0-9]{1,2} [0-9]{2}:[0-9]{2}:[0-9]{2})'
}


param_processors = [
    _process_syslog_time
]