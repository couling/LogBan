# Triggers

Triggers are are used to respond to events.  Typically they should take one of two forms:

 1. Colating events to publish other more meaningful events
 2. Taking action (eg: executing bans) on based on single meaningful events
 
These can be though of as:

 1. When to ban
 2. How to ban
 
## Creating your own Trigger

Plugins can hook into the existing configuration mechanism by registering a callback in `logban.trigger.trigger_types`.  All fields named in a config section will be passed as named parameters to your trigger configuration method except `type`.  Addationally `trigger_id` will be set to the name of the section. 

For example a config file in `/etc/logban/triggers/` could contain:

    [user-specified-trigger]
    type = my_plugin_trigger
    listen_for_event = "some_event"
    publish_event = "other_event"

Your code might look something like this:


    from logban.core import publish_event, register_action
    from logban.config import deep_merge_config
    
    class MyPluginTrigger:
    
        def __init__(self, id, to_publish):
            self.id = id
            self.to_publish = to_publish
        
        # Super simple trigger, just publishes a new event
        # When it recieves one with the same params
        def event(event, **params):
            publish_event(self.to_publish, **params)
    
    
    # Callback to configure the trigger
    def configure_my_plugin_trigger(trigger_id, config):
        # the above config sets trigger_id to 'user-specified-trigger'
        config_full = {
            'listen_for_event: 'some_default',
            'publish_event': 'some_other_default'
        }
        deep_merge_config(config_full,config)
        trigger = MyPluginTrigger(trigger_id, full_config['publish_event'])
        regist_action(full_config['listen_for_event'], trigger.event)
    
    
    # Let the configuration know about this trigger type
    trigger_types['my_plugin_trigger'] = configure_my_plugin_trigger
    
## Executing Commands

Logban offers a convenience method for executing commands against the system:

    from logban.trigger import execute_command
    
    execute_command(*args, log_level=logging.ERROR, logger=_logger, expect_result=None)

This will execute a command and write its output (stdout and stderr) to a log.  If an `expect_result` is not set to `None` and the command does not return that result, an exception will be raised (`CalledProcessError`).