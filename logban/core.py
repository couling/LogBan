import os.path
import sqlalchemy.orm
import sqlalchemy.ext.declarative
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

    @staticmethod
    def initialize_db(path='/var/lib/logban/logban.sqlite3', **excess_args):
        global DBBase
        os.makedirs(os.path.dirname(path), exist_ok=True)
        DBSession._db_engine = sqlalchemy.create_engine('sqlite:///%s' % path, echo=True)
        DBBase.metadata.create_all(DBSession._db_engine)
        DBSession._open_new_session = sqlalchemy.orm.sessionmaker(bind=DBSession._db_engine)


########
# Misc #
########

def wrap_list(value):
    if isinstance(value, list):
        return value
    if value is None or value == '':
        return []
    return [value]
