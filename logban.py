#! /usr/bin/python3

from logban.config import load_config, build_daemon
from logban.filemonitor import file_monitor_loop


def main():
    core_config, filter_config, trigger_config = load_config()
    build_daemon(core_config, filter_config, trigger_config)
    file_monitor_loop()


if __name__ == '__main__':
    main()
