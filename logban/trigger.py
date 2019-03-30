import json
import sqlalchemy.orm

from datetime import datetime, timedelta

from logban.core import register_action, publish_event, DBBase, DBSession, wrap_list


###########
# Trigger #
###########

class GroupCounterTrigger(object):

    @staticmethod
    def configure(trigger_id, group_on, result_event, trigger_events=None, reset_events=None,
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
        relavent_params = {key: params[key] for key in self.group_on}
        trigger_key = json.dumps(relavent_params, sort_keys=True)
        with DBSession() as session:
            status = session.query(DBTriggerStatus).get((self.trigger_id, trigger_key))
            if status is None:
                status = DBTriggerStatus(
                    trigger_id=self.trigger_id,
                    status_key=trigger_key,
                    trigger_count=1,
                    last_time=time,
                    first_time=time
                )
            else:
                status.last_time = time
                status.trigger_count += 1
            for line in lines:
                status.lines.append(DBTriggerStatusLine(time=time, line=line))
            status.times.append(DBTriggerStatusTime(time=time))
            if status.trigger_count >= self.count:
                for time in status.times:
                    if time.time_triggered < status.last_triggered - self.timeout:
                        status.times.remove(time)
                        status.trigger_count -= 1
                if status.times_triggered >= self.count:
                    publish_event(
                        self.result_event,
                        lines=[line.triggered_line for line in status.lines],
                        time=time,
                        **relavent_params
                    )
            session.add(status)
            session.commit()

    def reset(self, event_name, time, lines, **params):
        pass


class DBTriggerStatus(DBBase):

    __tablename__ = 'trigger_status'

    trigger_id = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    status_key = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    trigger_count = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    last_time = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    first_time = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    lines = sqlalchemy.orm.relationship('DBTriggerStatusLine')
    times = sqlalchemy.orm.relationship('DBTriggerStatusTime')

    def __repr__(self):
        return "<DBTriggerStatus(trigger_id='%s', status_key='%s', times_triggered='%d',"\
               "last_triggered='%s', first_triggered='%s')>" % (
                self.trigger_id,
                self.status_key,
                self.times_triggered,
                self.last_triggered,
                self.first_triggered)


class DBTriggerStatusTime(DBBase):

    __tablename__ = 'trigger_times'

    id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.Sequence('trigger_time_seq'), primary_key=True)
    trigger_id = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    status_key = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    time = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    __table_args__ = (sqlalchemy.ForeignKeyConstraint(['trigger_id', 'status_key'],
                                                      ['trigger_status.trigger_id', 'trigger_status.status_key'],
                                                      ondelete="CASCADE"),{})

    def __repr__(self):
        return "<DBTriggerStatusTime(trigger_id='%s', status_key='%s', time_triggered='%s')>" % (
                self.trigger_id,
                self.status_key,
                self.time_triggered)


class DBTriggerStatusLine(DBBase):

    __tablename__ = 'trigger_lines'

    id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.Sequence('trigger_line_seq'), primary_key=True)
    trigger_id = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    status_key = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    time = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    line = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    __table_args__ = (sqlalchemy.ForeignKeyConstraint(['trigger_id', 'status_key'],
                                                      ['trigger_status.trigger_id', 'trigger_status.status_key'],
                                                      ondelete="CASCADE"),{})

    def __repr__(self):
        return "<DBTriggerStatusLine(trigger_id='%s', status_key='%s',"\
               " triggered_time='%d', triggered_line='%s')>" % (
                self.trigger_id,
                self.status_key,
                self.triggered_time,
                self.triggered_line)


trigger_types = {
    'group_counter': GroupCounterTrigger.configure
}