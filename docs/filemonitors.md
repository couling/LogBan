# Log Monitors

There is very little architecture provided for additional log monitors however they are technically possible.  When creating a new file monitor the main pitfall is to avoid confusing the existing code.  You will need to ensure that files monitored by your new monitor are not confused with files to be monitored by iNotify.  It is therefore recommended to use a URI syntax rather than a raw file path.

The basic principle is that you need to register instances of your monitor in `logban.filemonitor.file_monitors`.  Your monitor should be a subclass of `logban.filemonitor.AbstractFileMonitor` but any object with a `filters` list and a `shutdown(self)` method should be fine.  The `filters` list will be automatically populated with filter callbacks.

Lets say you want to define a new monitor type in for use in `/etc/logban/filters/*`.  Your filter might use `mymonitor://` entries:

    mymonitor://log_path  |  access_denied | ^Access denied for {rhost}$

To setup `mymonitor://` as a new monitor type:

```python
import logging
import logban.config
import logban.core
import logban.filemonitor
import threading

_logger = logging.getLogger(__name__)


class MyFileMonitor(logban.filemonitor.AbstractFileMonitor):

     def __init__(self, file_path):
         super().__init__()
         self.file_path = file_path

     def run(self):
         # Monitor log
         # When you recieve a new line (new_line)
         for line_filter in self.filters:
             line_filter.filter_line(new_line)
     
     def shutdown(self):
         # Shut down this monitor
         pass

def run_monitor_thread(monitor):
    threading.Thread(target=monitor.run)

# On module load
for log, _ in logban.config.filter_config.items()
    if log.startswith('mymonitor://'):
        _logger.debug("Setting up monitor for %s", log)
        new_monitor = MyFileMonitor(log)
        # Delay the starting a thread until the main loop has started!
        logban.core.main_loop.call_soon(run_monitor_thread, new_monitor)
```

Notice how the above code doesn't actually care about the creation of filters or events.  This is done for you.  All your code actually has to do is publish lines to its filters.