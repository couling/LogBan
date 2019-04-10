# Logban Plugins

All modules and packages placed here will be loaded recursivly.  No action will be taken beyond loading the modules, so
the modules are responsible for wiring themselves in. 

Package names will be `logban.plugins.` ... a module `example.py` will be `logban.plugins.example.py`.

The following packages are guaranteed to have already been loaded to prevent circular dependencies:

 - logban.core
 - logban.config
 - logban.filemonitor
 - logban.filter
 - logban.trigger
 
 Logging will also have been configured correctly and modules are free to emit log messages during
 load.  This is indeed encouraged.
 
 **Warning:** DO NOT modify `logban.plugins.__init__.py`.  This is loaded at an earlier stage in the program and the 
 above guarantees are not applied.  If you need `__init__.py` actions then create your own package instead of a single
 module.