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


core_config = {}
filter_config = {}
trigger_config = {}


def load_config():
    opt_list, _ = getopt(sys.argv[1:], '', ['config-path='])
    opt_list = {option[2:].replace('-','_'): value for option, value in opt_list}
    load_config_files(**opt_list)


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
            logban.core.deep_merge_dict(existing, ConfigObj(config_path))
    else:
        for file_path in os.listdir(config_path):
            if file_path.endswith('.conf'):
                file_path = os.path.join(config_path, file_path)
                logban.core.deep_merge_dict(existing, ConfigObj(file_path))


def build_daemon():
    global core_config, filter_config, trigger_config

    # Configure logging
    logban.core.initialize_logging(**core_config.get('log', {}))

    # Load plugins here so that logging has been setup, but all else can be modified by plugins
    load_plugin_modules()

    # Open database connection
    logban.core.initialize_db(core_config.get('db', {}))

    # Setup file monitors and filters
    for file_path, filter_conf in filter_config.items():
        file_path = os.path.realpath(file_path)
        try:
            file_monitor = logban.filemonitor.all_file_monitors[file_path]
        except KeyError:
            file_monitor = logban.filemonitor.FileMonitor(file_path)
            logban.filemonitor.all_file_monitors[file_path] = file_monitor
        for config in filter_conf:
            new_filter = logban.filter.LogFilter(**config)
            file_monitor.filters.append(new_filter)

    # Setup triggers
    for trigger_id, config in trigger_config.items():
        builder = logban.trigger.trigger_types[config['type']]
        config = config.copy()
        del config['type']
        builder(trigger_id, config)


def load_plugin_modules(package=logban.plugins):
    for finder, module_name, is_package in pkgutil.iter_modules(package.__path__):
        module_name = "%s.%s" % (package.__name__, module_name)
        _logger.debug("Initializing %s", module_name)
        module = importlib.import_module(module_name)
        if is_package:
            load_plugin_modules(module)
