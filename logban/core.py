import os.path
import sqlalchemy.orm
import sqlalchemy.ext.declarative

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


# This class only works if single threaded!
# Forks must not happen with open sessions and pthreads are completely out
class DBSession:

    __db_engine = None
    _db_session = None
    __open_new_session = None
    __ref_count = 0

    def __init__(self):
        self.is_commit = False

    def __enter__(self):
        if DBSession.__ref_count == 0:
            DBSession._db_session = DBSession.__open_new_session()
        DBSession.__ref_count += 1
        DBSession._db_session.begin_nested()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_commit:
            DBSession._db_session.commit()
        else:
            DBSession._db_session.rollback()
        DBSession.__ref_count -= 1
        if DBSession.__ref_count == 0:
            DBSession._db_session.close()
            DBSession._db_session = None

    def __getattr__(self, name):
        return getattr(DBSession._db_session, name)

    def commit(self):
        self.is_commit = True

    def rollback(self):
        self.is_commit = False

    @staticmethod
    def initialize_db(path='/var/lib/logban/logban.sqlite3', **excess_args):
        global DBBase
        os.makedirs(os.path.dirname(path), exist_ok=True)
        DBSession.__db_engine = sqlalchemy.create_engine('sqlite:///%s' % path, echo=True)
        DBBase.metadata.create_all(DBSession.__db_engine)
        DBSession.__open_new_session = sqlalchemy.orm.sessionmaker(bind=DBSession.__db_engine)

########
# Misc #
########

def wrap_list(value):
    if isinstance(value, list):
        return value
    if value is None or value == '':
        return []
    return [value]
