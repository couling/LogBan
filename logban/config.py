from configobj import ConfigObj
from getopt import getopt
import importlib
import os
import os.path
import pkgutil
import re
import sys
import logging

import logban.core
import logban.filemonitor
import logban.filter
import logban.trigger
import logban.plugins


_logger = logging.getLogger(__name__)


def load_config():
    opt_list, _ = getopt(sys.argv[1:], '', ['config-path='])
    opt_list = {option[2:].replace('-','_'): value for option, value in opt_list}
    return load_config_files(**opt_list)


def load_config_files(config_path='/etc/logban'):
    global db_engine
    # Load core config
    core_config = ConfigObj(os.path.join(config_path, 'logban.conf'))
    filter_config = load_config_filters(os.path.join(config_path, 'filters'))
    trigger_config = load_config_objects(os.path.join(config_path, 'triggers'))
    return core_config, filter_config, trigger_config


def load_config_filters(config_path, filters=None):
    filter_re = re.compile(r'^ *(?P<log_path>[^#|]*[^#| ]+) *\| *(?P<event>[^ |]+) *\| *(?P<pattern>.+) *$')
    if filters is None:
        filters = {}
    for filter_path in os.listdir(config_path):
        filter_path = os.path.join(config_path, filter_path)
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


def load_config_objects(config, triggers=None):
    if triggers is None:
        triggers = {}
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
    # Configure logging
    logban.core.initialize_logging(**core_config.get('log', default={}))

    # Load plugins here so that logging has been setup, but all else can be modified by plugins
    load_plugin_modules()

    # Open database connection
    logban.core.initialize_db(**core_config.get('db', default={}))

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
        builder(trigger_id=trigger_id, **{key: value for key, value in config.items() if key != 'type'})

def load_plugin_modules(package=logban.plugins):
    for finder, module_name, is_pacakge in pkgutil.iter_modules(package.__path__):
        module_name = "%s.%s" % (package.__name__, module_name)
        _logger.debug("Initializing %s", module_name)
        module = importlib.import_module(module_name)
        if is_pacakge:
            load_plugin_modules(module)
