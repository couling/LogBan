import iptc
import json
import sqlalchemy.orm
import logging

from datetime import timedelta

from logban.core import register_action, publish_event, DBBase, DBSession, wrap_list


_logger = logging.getLogger(__name__)

def _trigger_key(key):
    return json.dumps(key, sort_keys=True)


class GroupCounterTrigger(object):

    @staticmethod
    def configure(trigger_id, result_event, group_on=None, trigger_events=None, reset_events=None,
                  count=5, timeout='2592000', **ignored_params):
        new_trigger = GroupCounterTrigger(trigger_id, wrap_list(group_on), result_event, count, int(timeout))
        for event in wrap_list(trigger_events):
            register_action(event, new_trigger.trigger)
        for event in wrap_list(reset_events):
            register_action(event, new_trigger.reset)

    def __init__(self, trigger_id, group_on, result_event, count, timeout):
        self.group_on = wrap_list(group_on)
        self.trigger_id = trigger_id
        self.result_event = result_event
        self.count = int(count)
        self.timeout = timedelta(seconds=int(timeout))

    def trigger(self, event_name, time, lines, **params):
        relevant_params = self._relevant_params(params)
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
            else:
                status.last_time = time
                status.trigger_count += 1
            expiry_time = status.last_time - self.timeout
            for previous_trigger_time in status.times:
                if previous_trigger_time.time < expiry_time:
                    status.times.remove(previous_trigger_time)
                    status.trigger_count -= 1
            _logger.info("%s: Strike %d of %d for %s", self.trigger_id,
                          status.trigger_count, self.count, relevant_params)
            if status.trigger_count >= self.count:
                publish_event(
                    self.result_event,
                    lines=[(line.log, line.time, line.line) for line in status.lines]+lines,
                    time=time,
                    **relevant_params
                )
                session.query(_DBTriggerStatus).filter_by(trigger_id=self.trigger_id, status_key=trigger_key).delete()
            else:
                status.times.append(_DBTriggerStatusTime(time=time))
                for log, line_time, line in lines:
                    status.lines.append(_DBTriggerStatusLine(log=log, time=line_time, line=line))
                session.add(status)
            session.commit()

    def reset(self, event_name, time, lines, **params):
        _logger.debug("%s: reset to 0 %s", self.trigger_id, self._relevant_params(params))
        trigger_key = _trigger_key(self._relevant_params(params))
        with DBSession() as session:
            session.query(_DBTriggerStatus).filter_by(trigger_id=self.trigger_id, status_key=trigger_key).delete()

    def _relevant_params(self, params):
        return {key: params[key] for key in self.group_on}


class BanTrigger(object):

    @staticmethod
    def configure(trigger_id, trigger_events=None, ban_time=2592000, probation_time=2592000,
                  repeat_scale=2, ip_param='rhost', **ignored_params):
        new_trigger = BanTrigger(trigger_id, ban_time, probation_time, repeat_scale, ip_param)
        for event in wrap_list(trigger_events):
            register_action(event, new_trigger.trigger)

    def __init__(self, trigger_id, ban_time, probation_time, repeat_scale, ip_param):
        self.trigger_id = trigger_id
        self.ban_time = timedelta(seconds=int(ban_time))
        self.probation_time = timedelta(seconds=int(probation_time))
        self.repeat_scale = repeat_scale
        self.ip_param = ip_param

    def trigger(self, event, time, lines, **params):
        ip = params[self.ip_param]
        with DBSession() as session:
            trigger_key = _trigger_key(ip)
            status = session.query(_DBTriggerStatus).get((self.trigger_id, trigger_key))
            if status is None:
                ban_now = True
                status = _DBTriggerStatus(
                    trigger_id=self.trigger_id,
                    status_key=trigger_key,
                    trigger_count=0,
                    first_time=time
                )
            else:
                ban_now = status.status != 'BAN'
                status.last_time=time
                status.trigger_count += 1
            for log, line_time, line in lines:
                status.lines.append(_DBTriggerStatusLine(log=log, time=line_time, line=line))
            if ban_now:
                status.status = 'BAN'
                status.last_time = time
                status.trigger_count += 1
                status.times.append(_DBTriggerStatusTime(time=time))
                _logger.log(logging.NOTICE, "%s: Banning %s", self.trigger_id, ip)
                self.ban_ip(ip)
            else:
                _logger.debug("%s: Skipping duplicate ban: %s", self.trigger_id, ip)
            session.add(status)
            session.commit()

    def ban_ip(self, ip):
        try:
            rule = iptc.Rule()
            rule.src = ip
            rule.create_target('DROP')
            iptc.Chain(iptc.Table(iptc.Table.FILTER), 'INPUT').insert_rule(rule)
        except iptc.ip4tc.IPTCError as e:
            _logger.error("Failed to ban %s because %s", ip, str(e))


class _DBTriggerStatus(DBBase):

    __tablename__ = 'trigger_status'

    trigger_id = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    status_key = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    status = sqlalchemy.Column(sqlalchemy.String)
    first_time = sqlalchemy.Column(sqlalchemy.DateTime)
    last_time = sqlalchemy.Column(sqlalchemy.DateTime)
    trigger_count = sqlalchemy.Column(sqlalchemy.Integer)
    lines = sqlalchemy.orm.relationship('_DBTriggerStatusLine')
    times = sqlalchemy.orm.relationship('_DBTriggerStatusTime')


class _DBTriggerStatusTime(DBBase):

    __tablename__ = 'trigger_times'

    id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.Sequence('trigger_time_seq'), primary_key=True)
    trigger_id = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    status_key = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    time = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    __table_args__ = (sqlalchemy.ForeignKeyConstraint(
        ['trigger_id', 'status_key'],
        ['trigger_status.trigger_id', 'trigger_status.status_key'],
        ondelete="CASCADE"
    ),{})


_trigger_times_index = sqlalchemy.Index(
    'trigger_times_index',
    _DBTriggerStatusTime.trigger_id,
    _DBTriggerStatusTime.status_key
)


class _DBTriggerStatusLine(DBBase):

    __tablename__ = 'trigger_lines'

    id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.Sequence('trigger_line_seq'), primary_key=True)
    trigger_id = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    status_key = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    log = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    time = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    line = sqlalchemy.Column(sqlalchemy.String, nullable=False)
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
    'ip_ban': BanTrigger.configure,
}
