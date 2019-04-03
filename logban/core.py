import logging
import os.path
import sqlalchemy.orm
import sqlalchemy.ext.declarative
import sys
import threading


##########
# Events #
##########

event_actions = {}


def register_action(event, action):
    try:
        event_actions[event].append(action)
    except KeyError:
        event_actions[event] = [action]


def publish_event(event, **details):
    _logger.debug("Event %s: %s", event, details)
    try:
        actions = event_actions[event]
    except KeyError:
        # Avoid excessive exceptions, If an event is published then assume it will be again and create an event
        # even if there are no listeners
        actions = []
        event_actions[event] = actions
    for action in actions:
        action(event, **details)


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
        self.is_commit = False
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


class _DBLogFilter(logging.Filter):

    def __init__(self, logger):
        super().__init__()
        self.logger = logger


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
    format = "%(asctime)s %(name)s [%(levelname)-6.6s]  %(message)s"
    handlers = []
    if log_path != None:
        handlers.append(logging.FileHandler(filename=log_path))
    else:
        handlers.append(logging.StreamHandler(stream=sys.stdout))

    logging.basicConfig(level=logging._nameToLevel[level], format=format,
                        handlers=handlers, datefmt=date_format)

    if fine_grained_level is not None:
        for key, value in fine_grained_level.items():
            logging.getLogger(key).level=logging._nameToLevel[value]

    _logger.log(logging.NOTICE, "Logging Started")

