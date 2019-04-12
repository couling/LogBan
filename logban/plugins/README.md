# Logban Plugins

All modules and packages placed here will be loaded recursively.  No action will be taken beyond loading the modules; the modules are responsible for wiring themselves in. 

For example `my_plugin.py` placed in this directory will be loaded as `logban.plugins.my_plugin`.

At the stage plugin modules are loaded, following packages are guaranteed to have already been loaded to prevent circular dependencies:

    logban.core
    logban.config
    logban.filemonitor
    logban.filter
    logban.trigger
 
Logging will have been configured correctly based on configuration and modules are free to emit log messages during load.  This is indeed encouraged.
 
 **Warning:** DO NOT modify `logban.plugins.__init__.py`.  This is loaded at an earlier stage in the program and the above guarantees are not applied.  If you need `__init__.py` actions then create your own package instead of a single
 module.