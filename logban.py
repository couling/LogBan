#! /usr/bin/python3

from logban.config import load_config, build_daemon
from logban.core import run_main_loop


def main():
    load_config()
    build_daemon()
    run_main_loop()


if __name__ == '__main__':
    main()
