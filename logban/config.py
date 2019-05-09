from configobj import ConfigObj
from getopt import getopt
import os
import os.path
import re
import logging

from logban.core import deep_merge_dict

_logger = logging.getLogger(__name__)


core_config = {}
filter_config = {}
trigger_config = {}


def parse_args(args):
    options, actions = getopt(args, '', ['config-path='])
    return {option[2:].replace('-','_'): value for option, value in options}, actions


def load_config_files(config_path='/etc/logban'):
    global db_engine, core_config, filter_config, trigger_config
    # Load core config
    load_config_objects(core_config, os.path.join(config_path, 'logban.conf'))
    load_config_filters(filter_config, os.path.join(config_path, 'filters'))
    load_config_objects(trigger_config, os.path.join(config_path, 'triggers'))


def load_config_filters(existing, config_path):
    filter_re = re.compile(r'^ *(?P<log_path>[^#|]*[^#| ]+) *\| *(?P<event>[^ |]+) *\| *(?P<pattern>.+) *$')
    for filter_path in os.listdir(config_path):
        if filter_path.endswith('.conf'):
            filter_path = os.path.join(config_path, filter_path)
            with open(filter_path) as filter_file:
                for line in filter_file:
                    match = filter_re.match(line)
                    if match is not None:
                        params = match.groupdict()
                        if params['log_path'] not in existing:
                            existing[params['log_path']] = [params]
                        else:
                            existing[params['log_path']].append(params)


def load_config_objects(existing, config_path):
    if os.path.isfile(config_path):
        if config_path.endswith('.conf'):
            deep_merge_dict(existing, ConfigObj(config_path))
    else:
        for file_path in os.listdir(config_path):
            if file_path.endswith('.conf'):
                file_path = os.path.join(config_path, file_path)
                deep_merge_dict(existing, ConfigObj(file_path))
