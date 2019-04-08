import re
import logging

from datetime import datetime, timedelta

from logban.core import publish_event


_logger = logging.getLogger(__name__)


class LogFilter(object):

    def __init__(self, event, log_path, pattern):
        self.event = event
        self.source_pattern = pattern
        self.pattern = re.compile(pattern)
        self.log_path = log_path
        actual_pattern = pattern.format(**named_groups)
        _logger.debug("Pattern %s", pattern)
        _logger.debug("Becomes %s", actual_pattern)
        self.pattern = re.compile(actual_pattern)

    def filter_line(self, line):
        found = self.pattern.search(line)
        if found is not None:
            _logger.debug("Matched log %s line: %s", self.log_path, line)
            params = found.groupdict()
            for processor in param_processors:
                processor(params)
            if 'time' not in params:
                params['time'] = datetime.now()
            publish_event(self.event, log_path=self.log_path,
                          lines=[(self.log_path, params['time'], line)], **params)


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
    'rhost': r"(?P<rhost>([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)|"
             r"|(([0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|"
             r"([0-9a-fA-F]{1,4}:){1,7}:|"
             r"([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|"
             r"([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|"
             r"([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|"
             r"([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|"
             r"([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|"
             r"[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|"
             r":((:[0-9a-fA-F]{1,4}){1,7}|:)|"
             r"fe80:(:[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}|"
             r"::(ffff(:0{1,4}){0,1}:){0,1}((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}(25[0-5]|"
             r"(2[0-4]|1{0,1}[0-9]){0,1}[0-9])|"
             r"([0-9a-fA-F]{1,4}:){1,4}:((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}"
             r"(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])"
             r"))",
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