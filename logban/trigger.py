import iptc
import json
import sqlalchemy.orm

from datetime import datetime, timedelta

from logban.core import register_action, publish_event, DBBase, DBSession, wrap_list


def _trigger_key(id, params):
    return json.dumps({'i': id, 'j': params}, sort_keys=True)


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
        trigger_key = _trigger_key(self.trigger_id, relevant_params)
        with DBSession() as session:
            status = session.query(_DBTriggerStatus).get(trigger_key)
            if status is None:
                status = _DBTriggerStatus(
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
            if status.trigger_count >= self.count:
                publish_event(
                    self.result_event,
                    lines=[(line.log, line.time, line.line) for line in status.lines]+lines,
                    time=time,
                    **relevant_params
                )
                session.query(_DBTriggerStatus).filter_by(status_key=trigger_key).delete()
            else:
                status.times.append(_DBTriggerStatusTime(time=time))
                for log, line_time, line in lines:
                    status.lines.append(_DBTriggerStatusLine(log=log, time=line_time, line=line))
                session.add(status)
            session.commit()

    def reset(self, event_name, time, lines, **params):
        trigger_key = _trigger_key(self.trigger_id, self._relevant_params(params))
        with DBSession() as session:
            session.query(_DBTriggerStatus).filter_by(status_key=trigger_key).delete()

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
            trigger_key = _trigger_key(self.trigger_id, ip)
            status = session.query(_DBTriggerStatus).get(trigger_key)
            if status is None:
                status = _DBTriggerStatus(
                    status_key=trigger_key,
                    trigger_count=1,
                    last_time=time,
                    first_time=time
                )
            else:
                status.last_time=time
                status.trigger_count += 1
            for log, line_time, line in lines:
                status.lines.append(_DBTriggerStatusLine(log=log, time=line_time, line=line))
            status.times.append(_DBTriggerStatusTime(time=time))
            session.add(status)
            rule = iptc.Rule()
            rule.src = ip
            rule.create_target('DROP')
            iptc.Chain(iptc.Table(iptc.Table.FILTER), 'INPUT').insert_rule(rule)
            session.commit()


class _DBTriggerStatus(DBBase):

    __tablename__ = 'trigger_status'

    status_key = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    first_time = sqlalchemy.Column(sqlalchemy.DateTime)
    last_time = sqlalchemy.Column(sqlalchemy.DateTime)
    trigger_count = sqlalchemy.Column(sqlalchemy.Integer)
    lines = sqlalchemy.orm.relationship('_DBTriggerStatusLine')
    times = sqlalchemy.orm.relationship('_DBTriggerStatusTime')


class _DBTriggerStatusTime(DBBase):

    __tablename__ = 'trigger_times'

    id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.Sequence('trigger_time_seq'), primary_key=True)
    status_key = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    time = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    __table_args__ = (sqlalchemy.ForeignKeyConstraint(
        ['status_key'],
        ['trigger_status.status_key'],
        ondelete="CASCADE"
    ),{})


class _DBTriggerStatusLine(DBBase):

    __tablename__ = 'trigger_lines'

    id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.Sequence('trigger_line_seq'), primary_key=True)
    status_key = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    log = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    time = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    line = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    __table_args__ = (sqlalchemy.ForeignKeyConstraint(
        ['status_key'],
        ['trigger_status.status_key'],
        ondelete="CASCADE"
    ), {})


trigger_types = {
    'group_counter': GroupCounterTrigger.configure,
    'ip_ban': BanTrigger.configure,
}
