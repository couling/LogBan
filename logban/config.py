from configobj import ConfigObj
from getopt import getopt
import os
import os.path
import re
import sys

import logban.core
import logban.filemonitor
import logban.filter
import logban.trigger


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
    return core_config, filter_config, trigger_config


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


def load_config_triggers(config, triggers=None):
    if triggers is None:
        triggers = {}
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


def build_daemon(core_config, filter_config, trigger_config):
    global file_monitors
    # Open database connection
    logban.core.DBSession.initialize_db(**core_config.get('db', default={}))

    # Setup file monitors and filters
    for file_path, filter_conf in filter_config.items():
        file_path = os.path.realpath(file_path)
        if file_path not in logban.filemonitor.file_monitors:
            logban.filemonitor.register_file(file_path)
        for config in filter_conf:
            new_filter = logban.filter.LogFilter(**config)
            logban.filemonitor.file_monitors[file_path].filters.append(new_filter)

    # Setup triggers
    for trigger_id, config in trigger_config.items():
        builder = logban.trigger.trigger_types[config['type']]
        builder(trigger_id=trigger_id, **config)
