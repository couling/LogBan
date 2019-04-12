from datetime import datetime
import asyncio
import logging
import os.path
import sqlalchemy.orm
import sqlalchemy.ext.declarative
import sys
import threading
import json


############
# Database #
############

DBBase = sqlalchemy.ext.declarative.declarative_base()


class DBSession:

    _db_engine = None
    _db_session_dict = {}
    _open_new_session = None
    _ref_count = 0

    def __init__(self):
        self.is_commit = None
        self._parent = None
        self._db_session = None

    def __enter__(self):
        thread_id = threading.get_ident()
        self._parent = DBSession._db_session_dict.get(thread_id, None)
        if self._parent is None:
            self._db_session = DBSession._open_new_session()
        else:
            self._db_session = self._parent._db_session
        self._db_session.begin_nested()
        DBSession._db_session_dict[thread_id] = self
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_commit is None:
            self.is_commit = exc_type is None
        if self.is_commit:
            self._db_session.commit()
        else:
            self._db_session.rollback()
        if self._parent is None:
            self._db_session.close()
            del DBSession._db_session_dict[threading.get_ident()]
        else:
            DBSession._db_session_dict[threading.get_ident()] = self._parent

    def __getattr__(self, name):
        return getattr(self._db_session, name)

    def commit(self):
        self.is_commit = True

    def rollback(self):
        self.is_commit = False


def initialize_db(path='/var/lib/logban/logban.sqlite3', **excess_args):
    _logger.debug("Initializing DB %s", path)
    global DBBase
    os.makedirs(os.path.dirname(path), exist_ok=True)
    DBSession._db_engine = sqlalchemy.create_engine('sqlite:///%s' % path)
    DBBase.metadata.create_all(DBSession._db_engine)
    DBSession._open_new_session = sqlalchemy.orm.sessionmaker(bind=DBSession._db_engine)


##########
# Events #
##########

event_listeners = {}
main_loop = asyncio.new_event_loop()


def run_main_loop():
    global _main_loop_thread_id
    _main_loop_thread_id = threading.get_ident()
    main_loop.run_forever()


def register_action(event, action):
    try:
        event_listeners[event].append(action)
    except KeyError:
        event_listeners[event] = [action]


def publish_event(event, event_time=None, **params):
    if event_time is not None:
        _register_event_for_later(event, event_time, params)
    else:
        if event_time is not None:
            params['event_time'] = event_time
        main_loop.call_soon_threadsafe(_fire_event, event, params)


def _register_event_for_later(event, event_time, params):
    # We only access the database from the main thread
    # If this isn't the main thread then schedule the same action using the main_loop
    if threading.get_ident() == _main_loop_thread_id:
        _logger.debug("Scheduled event %s for %s: %s", event, event_time, params)
        with DBSession() as session:
            event_object = _DBFutureEvent(event=event, event_time=event_time, params=json.dumps(params))
            session.add(event_object)
    else:
        main_loop.call_soon_threadsafe(_register_event_for_later, event_time, params)


def _fire_event(event, params):
    _logger.debug("Event %s: %s", event, params)
    try:
        event_action_list = event_listeners[event]
        for action in event_action_list:
            try:
                action(event, **params)
            except:
                _logger.exception("Failure with event %s", event)
    except KeyError:
        _logger.warning("Published event %s has no listeners, this warning will not be repeated", event)
        event_listeners[event] = []


def _fire_timed_events():
    _logger.debug("Tick... checking timed events")
    with DBSession() as session:
        for event_details in session.query(_DBFutureEvent).filter(_DBFutureEvent.event_time <= datetime.now())\
                .order_by(_DBFutureEvent.event_time):
            params = json.loads(event_details.params)
            params['event_time'] = event_details.event_time
            _fire_event(event_details.event, params)
            session.delete(event_details)
    main_loop.call_later(60, _fire_timed_events)


main_loop.call_later(0, _fire_timed_events)


class _DBFutureEvent(DBBase):

    __tablename__ = 'future_event'

    id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.Sequence('trigger_line_seq'), primary_key=True)
    event = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    params = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    event_time = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)


_future_event_time_index = sqlalchemy.Index(
    'future_event_time_index',
    _DBFutureEvent.event_time
)


########
# Misc #
########

def wrap_list(value):
    if isinstance(value, list):
        return value
    if value is None or value == '':
        return []
    return [value]


_logger = logging.getLogger(__name__)


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


def deep_merge_dict(existing_config, new_config):
    for key, value in new_config.items():
        if key in existing_config and isinstance(existing_config[key], dict) and isinstance(value, dict):
            deep_merge_dict(existing_config[key], value)
        else:
            existing_config[key] = value
