import logging
import logban
import os.path
import pkgutil
import importlib
import sys

import logban.config
import logban.core
import logban.filemonitor
import logban.filter
import logban.plugins
import logban.trigger

_logger = logging.getLogger(__name__)


def main():
    options, actions = logban.config.parse_args(sys.argv[1:])
    logban.config.load_config_files(**options)
    for action in actions:
        if action == 'run':
            initialize_daemon()
            logban.core.run_main_loop()
        elif action == 'initdb':
            load_plugin_modules()
            logban.core.initialize_db(logban.config.core_config.get('db', {}))


def initialize_daemon():

    # Configure logging
    initialize_logging(**logban.config.core_config.get('log', {}))

    # Load plugins here so that logging has been setup, but all else can be modified by plugins
    load_plugin_modules()

    # Open database connection
    logban.core.initialize_db(logban.config.core_config.get('db', {}))

    # Setup file monitors and filters
    for file_path, filter_conf in logban.config.filter_config.items():
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
    for trigger_id, config in logban.config.trigger_config.items():
        builder = logban.trigger.trigger_types[config['type']]
        config = config.copy()
        del config['type']
        builder(trigger_id, config)


def initialize_logging(level='INFO', log_path=None, date_format='%Y-%m-%d %H:%M:%S',
                       fine_grained_level=None):
    logging.NOTICE = logging.ERROR + 5
    logging._levelToName[logging.NOTICE] = 'NOTICE'
    logging._nameToLevel['NOTICE'] = logging.NOTICE
    line_format = "%(asctime)s %(name)s [%(levelname)-7.7s]  %(message)s"
    handlers = []
    if log_path is not None:
        handlers.append(logging.FileHandler(filename=log_path))
    else:
        handlers.append(logging.StreamHandler(stream=sys.stdout))

    logging.basicConfig(level=logging._nameToLevel[level], format=line_format,
                        handlers=handlers, datefmt=date_format)

    if fine_grained_level is not None:
        for key, value in fine_grained_level.items():
            logging.getLogger(key).level = logging._nameToLevel[value]

    _logger.log(logging.NOTICE, "Logging Started")


def load_plugin_modules(package=logban.plugins):
    for finder, module_name, is_package in pkgutil.iter_modules(package.__path__):
        module_name = "%s.%s" % (package.__name__, module_name)
        _logger.debug("Initializing %s", module_name)
        module = importlib.import_module(module_name)
        if is_package:
            load_plugin_modules(module)
