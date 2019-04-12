# Logban Plugins

### From [logban/plugins/README.md](../logban/plugins/README.md)

Logban will automatically load all modules and packages recursively contained in [`logban.plugins`](../logban/plugins).  Logban will not take any other action; the modules are responsible for wiring themselves in. 

For example `my_plugin.py` placed in this directory will be loaded as `logban.plugins.my_plugin`.

*More can be read on the Logban's load phases below but for brevity...* At the stage plugin modules are loaded, following packages are guaranteed to have already been loaded to prevent circular dependencies::

    logban.core
    logban.config
    logban.filemonitor
    logban.filter
    logban.trigger
 
Logging will have been configured correctly based on configuration and modules are free to emit log messages during load.  This is indeed encouraged.
 
 **Warning:** DO NOT modify `logban.plugins.__init__.py`.  This is loaded at an earlier stage in the program and the above guarantees are not applied.  If you need `__init__.py` actions then create your own package instead of a single
 module. 

## Threadding

Logban is deliberately single threaded (mostly).  The database must not be accessed from another thread as SQLite databases cannot handle multiple simultaneous connections.  Code has been written on the assumption the database access will always be single threaded.

Therefore any activity which requires database access must be executed on the main thread.  All events are executed on the main thread.  Where you are unsure, register a callback using:

    import logban.core

    def not_main_thread();
        logban.core.main_thread.call_soon_threadsafe(do_database_stuff_on_main, arg_value)

    def do_database_stuff_on_main(arg):
        with logban.core.DBSession() as session:
           session.query(.....) 


## Integration Points

Logban will not explicitly wire a module in, it will simply load it.  So plugins must wire themselves in using a number of integration points.

 - [Events](events.md)
 - [Custom Monitors](filemonitors.md)
 - [Filter augmentation](filters.md)
 - [Triggers](triggers.md)


## Load Phases

 1. Config is loaded blindly into dictionaries.
 2. Logging is initialized.
 3. Plugin modules are loaded
   - Plugin modules may
     - Read Config
     - Modify Config
     - Create custom file monitors
     - Add named regular expressions in `logban.filter.named_groups`
     - Add param processors in `logban.filter.param_processors`
     - Register custom trigger types in `logban.trigger.trigger_types`
   - Plugin modules must NOT 
     - start threads - instead register a callback using `logban.core.main_loop.call_soon()`
     - Publish events - instead register a callback using `logban.core.main_loop.call_soon()`
 4. Filters are created and wired into file monitors.
   - If file monitors do not already exist they will be created automatically
 5. Triggers are created using `logban.trigger.trigger_types` and wired into events
 6. The main thread enters `main_loop`.  Assuming the rules have been obeyed, the callbacks will be the setup phases deferred from stage 3.  This is the first time Logban becomes multithreaded
 7. Once the initial queue of callbacks has cleared events will begin to flow and Logban is  live.