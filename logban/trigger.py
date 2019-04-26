import json
import sqlalchemy.orm
import subprocess
import logging
import re

from abc import ABC, abstractmethod
from datetime import timedelta

from logban.core import register_action, publish_event, DBBase, DBSession, wrap_list, deep_merge_dict


_logger = logging.getLogger(__name__)


def _trigger_key(key):
    return json.dumps(key, sort_keys=True)


def _decode_trigger_key(key):
    return json.loads(key)


def exec_command(*args, log_level=logging.ERROR, logger=_logger, expect_result=0):
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Executing: %s", ' '.join(args))
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8')
    with process.stdout as output:
        for line in output:
            logger.log(log_level, "%s: %s", args[0], line[:-1])
    result = process.wait()
    if expect_result is not None and result != expect_result:
        raise subprocess.CalledProcessError(result, ' ', None, None)
    return result


class GroupCounterTrigger(object):

    @staticmethod
    def configure(trigger_id, config):
        config_full = {
            'group_on': {},
            'trigger_events': {},
            'reset_events': {},
            'count': '5',
            'timeout': '2592000'
        }
        deep_merge_dict(config_full, config)
        new_trigger = GroupCounterTrigger(trigger_id,
                                          wrap_list(config_full['group_on']),
                                          config_full['result_event'],
                                          config_full['count'],
                                          int(config_full['timeout']))
        for event in wrap_list(config['trigger_events']):
            register_action(event, new_trigger.trigger)
        for event in wrap_list(config['reset_events']):
            register_action(event, new_trigger.reset)

    def __init__(self, trigger_id, group_on, result_event, count, timeout):
        self.group_on = wrap_list(group_on)
        self.trigger_id = trigger_id
        self.result_event = result_event
        self.count = int(count)
        self.timeout = timedelta(seconds=int(timeout))

    def trigger(self, event, time, lines, **params):
        relevant_params = {key: params[key] for key in self.group_on}
        trigger_key = _trigger_key(relevant_params)
        with DBSession() as session:
            status = session.query(_DBTriggerStatus).get((self.trigger_id, trigger_key))
            if status is None:
                status = _DBTriggerStatus(
                    trigger_id=self.trigger_id,
                    status_key=trigger_key,
                    trigger_count=1,
                    last_time=time,
                    first_time=time
                )
                session.add(status)
            else:
                status.last_time = time
                status.trigger_count += 1
            expiry_time = status.last_time - self.timeout
            for previous_trigger_time in status.times:
                if previous_trigger_time.time < expiry_time:
                    status.times.remove(previous_trigger_time)
                    status.trigger_count -= 1
            _logger.info("%s: Strike %d of %d for %s caused by %s", self.trigger_id,
                         status.trigger_count, self.count, relevant_params, event)
            if status.trigger_count >= self.count:
                publish_event(
                    self.result_event,
                    lines=[(line.log, line.time, line.line) for line in status.lines]+lines,
                    time=time,
                    **relevant_params
                )
                session.query(_DBTriggerStatus).filter_by(
                    trigger_id=self.trigger_id, status_key=trigger_key
                ).delete()
            else:
                status.times.append(_DBTriggerStatusTime(time=time))
                for log, line_time, line in lines:
                    status.lines.append(_DBTriggerStatusLine(log=log, time=line_time, line=line))

    def reset(self, _, **params):
        relevant_params = {key: params[key] for key in self.group_on}
        _logger.debug("%s: reset to 0 %s", self.trigger_id, relevant_params)
        trigger_key = _trigger_key(relevant_params)
        with DBSession() as session:
            session.query(_DBTriggerStatus).filter_by(
                trigger_id=self.trigger_id, status_key=trigger_key
            ).delete()


class AbstractBanTrigger(ABC):

    def __init__(self, trigger_id, ban_time, probation_time, repeat_scale, ban_params):
        self.trigger_id = trigger_id
        self.ban_time = timedelta(seconds=int(ban_time))
        self.probation_time = timedelta(seconds=int(probation_time))
        self.repeat_scale = int(repeat_scale)
        self.ban_params = ban_params
        self.time_event = ".timer." + self.trigger_id

    def all_bans(self):
        with DBSession() as session:
            for ban in session.query(_DBTriggerStatus).filter_by(trigger_id=self.trigger_id):
                yield _decode_trigger_key(ban.status_key)

    def trigger(self, _, time, lines, **params):
        relevant_params = {key: params[key] for key in self.ban_params}
        trigger_key = _trigger_key(relevant_params)
        with DBSession() as session:
            status = session.query(_DBTriggerStatus).get((self.trigger_id, trigger_key))
            if status is None:
                ban_now = True
                status = _DBTriggerStatus(
                    trigger_id=self.trigger_id,
                    status_key=trigger_key,
                    trigger_count=0,
                    first_time=time
                )
                session.add(status)
            else:
                ban_now = status.status != 'BAN'
                status.last_time = time
                status.trigger_count += 1
            for log, line_time, line in lines:
                status.lines.append(_DBTriggerStatusLine(log=log, time=line_time, line=line))
            if ban_now:
                status.status = 'BAN'
                status.last_time = time
                status.trigger_count += 1
                status.times.append(_DBTriggerStatusTime(time=time))
                _logger.log(logging.NOTICE, "%s: Banning %s", self.trigger_id, trigger_key)
                self._ban(**relevant_params)
                probation_time = time + (self.ban_time * (self.repeat_scale ** (status.trigger_count - 1)))
                publish_event(self.time_event, event_time=probation_time, **relevant_params)
            else:
                _logger.debug("%s: Skipping duplicate ban: %s", self.trigger_id, trigger_key)

    def timer_action(self, event, event_time, **params):
        trigger_key = _trigger_key(params)
        with DBSession() as session:
            status = session.query(_DBTriggerStatus).get((self.trigger_id, trigger_key))
            if status is None:
                return
            if status.status == 'BAN':
                _logger.log(logging.NOTICE, "%s: Probation %s", self.trigger_id, trigger_key)
                self._unban(**params)
                status.status = 'PROBATION'
                publish_event(event, event_time=event_time + self.probation_time, **params)
            elif status.status == 'PROBATION':
                _logger.log(logging.NOTICE, "%s: Clear %s", self.trigger_id, trigger_key)
                session.query(_DBTriggerStatus).filter_by(
                    trigger_id=self.trigger_id, status_key=trigger_key
                ).delete()

    @abstractmethod
    def _ban(self, **params):
        pass

    @abstractmethod
    def _unban(self, **params):
        pass


class IptablesBanTrigger(AbstractBanTrigger):

    ipv4_re = re.compile(r"([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)")

    @staticmethod
    def configure(trigger_id, config):
        config_full = {
            'trigger_events': None,
            'ban_time': '2592000',
            'probation_time': '2592000',
            'repeat_scale': '2'
        }
        deep_merge_dict(config_full, config)
        new_trigger = IptablesBanTrigger(trigger_id,
                                         config_full['ban_time'],
                                         config_full['probation_time'],
                                         config_full['repeat_scale'])
        for event in wrap_list(config_full['trigger_events']):
            register_action(event, new_trigger.trigger)
        register_action(new_trigger.time_event, new_trigger.timer_action)
        new_trigger._initialize()

    def __init__(self, trigger_id, ban_time, probation_time, repeat_scale):
        super().__init__(trigger_id, ban_time, probation_time, repeat_scale, ['rhost'])
        self.iptables_chain = 'logban-' + self.trigger_id

    def _initialize(self):
        _logger.info("%s: Initializing", self.trigger_id)
        for iptables in ['iptables', 'ip6tables']:
            result = exec_command(
                iptables, '-C', 'INPUT', '-j', self.iptables_chain,
                log_level=logging.DEBUG,
                expect_result=None)
            if result != 0:
                exec_command(iptables, '-N', self.iptables_chain)
                exec_command(iptables, '-A', 'INPUT', '-j', self.iptables_chain)
                exec_command(iptables, '-A', self.iptables_chain, '-j', 'RETURN')
        for ban in self.all_bans():
            self._ban(**ban)

    def _ban(self, rhost):
        if self.ipv4_re.match(rhost):
            iptables = 'iptables'
        else:
            iptables = 'ip6tables'
        if exec_command(
                iptables, '-C', self.iptables_chain, '-s', rhost, '-j', 'DROP',
                log_level=logging.DEBUG, expect_result=None) == 0:
            _logger.warning("%s: ban already exists for %s", self.trigger_id, rhost)
        else:
            exec_command(iptables, '-I', self.iptables_chain, '1', '-s', rhost, '-j', 'DROP')

    def _unban(self, rhost):
        if self.ipv4_re.match(rhost):
            iptables = 'iptables'
        else:
            iptables = 'ip6tables'
        exec_command(iptables, '-D', self.iptables_chain, '-s', rhost, '-j', 'DROP')


class _DBTriggerStatus(DBBase):

    __tablename__ = 'trigger_status'

    trigger_id = sqlalchemy.Column(sqlalchemy.String(100),  primary_key=True)
    status_key = sqlalchemy.Column(sqlalchemy.String(1000), primary_key=True)
    status = sqlalchemy.Column(sqlalchemy.String(10))
    first_time = sqlalchemy.Column(sqlalchemy.DateTime)
    last_time = sqlalchemy.Column(sqlalchemy.DateTime)
    trigger_count = sqlalchemy.Column(sqlalchemy.Integer)
    lines = sqlalchemy.orm.relationship('_DBTriggerStatusLine')
    times = sqlalchemy.orm.relationship('_DBTriggerStatusTime')


class _DBTriggerStatusTime(DBBase):

    __tablename__ = 'trigger_times'

    id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.Sequence('trigger_time_seq'), primary_key=True)
    trigger_id = sqlalchemy.Column(sqlalchemy.String(100), nullable=False)
    status_key = sqlalchemy.Column(sqlalchemy.String(1000), nullable=False)
    time = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    __table_args__ = (sqlalchemy.ForeignKeyConstraint(
        ['trigger_id', 'status_key'],
        ['trigger_status.trigger_id', 'trigger_status.status_key'],
        ondelete="CASCADE"
    ), {})


_trigger_times_index = sqlalchemy.Index(
    'trigger_times_index',
    _DBTriggerStatusTime.trigger_id,
    _DBTriggerStatusTime.status_key
)


class _DBTriggerStatusLine(DBBase):

    __tablename__ = 'trigger_lines'

    id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.Sequence('trigger_line_seq'), primary_key=True)
    trigger_id = sqlalchemy.Column(sqlalchemy.String(100), nullable=False)
    status_key = sqlalchemy.Column(sqlalchemy.String(1000), nullable=False)
    log = sqlalchemy.Column(sqlalchemy.String(1000), nullable=False)
    time = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    line = sqlalchemy.Column(sqlalchemy.Text, nullable=False)
    __table_args__ = (sqlalchemy.ForeignKeyConstraint(
        ['trigger_id', 'status_key'],
        ['trigger_status.trigger_id', 'trigger_status.status_key'],
        ondelete="CASCADE"
    ), {})


_trigger_lines_index = sqlalchemy.Index(
    'trigger_lines_index',
    _DBTriggerStatusLine.trigger_id,
    _DBTriggerStatusLine.status_key
)


trigger_types = {
    'group_counter': GroupCounterTrigger.configure,
    'ip_ban': IptablesBanTrigger.configure,
}
