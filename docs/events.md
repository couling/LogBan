# Events

Events are the heart of Logban.  Filters check log lines and publish a named event when a match is found.  Triggers (the brains of Logban) process events, either taking direct action such as modifying firewall rules or grouping together events and publishing new events when a threshold has been reached.

Plugins can both publish events and register actions to be performed on events:

    from logban.core import register_action, publish_event

    def my_action(event, **params):
        print("Event %s with params %s", event, params)

    register_action('my_event', my_action)

    publish_event('my_event', rhost='127.0.0.2')

Will print:

    Event my_event with params {'rhost': '127.0.0.2'}

# Timed Events

Technically timed events are just events.  However if an `event_time` parameter is specified (as a `datetime.datetime` object) Logban will delay the actual publish of the event until at least the specified time.  Pending timed events are published once per minute.

Timed events are registered for in exactly the same way and the original `event_time` will be pass through as a parameter.  For example you can request a particular event is published tomorrow with:

    from logban.core import publish_event
    from datetime import datetime, timedelta
    
    publish_event('my_event', event_time=datetime.now() + timedelta(days=1), rhost='127.0.0.2')

Timed events are stored in the database by serializing to Json and so will persist even if Logban is restarted.