#!/usr/bin/python3

import os.path
import pyinotify


class EventHandler(pyinotify.ProcessEvent):

    def __init__(self):
        self.logs = {}

    def process_IN_CREATE(self, event):
        if not event.dir and event.pathname in self.logs:
            self.logs[event.pathname].reset()
            print ("Reset log %s" % event.pathname)

    def process_IN_DELETE(self, event):
        if not event.dir and event.pathname in self.logs:
            self.logs[event.pathname].close()

    def process_IN_MODIFY(self, event):
        if not event.dir and event.pathname in self.logs:
            self.logs[event.pathname].notify_change()

    def process_default(self, event):
        print(event)

    def register_filter(self, path, action):
        path = os.path.abspath(path)
        try:
            self.logs[path].append(action)
        except KeyError:
            self.logs[path] = MonitoredLog(log_file=path, actions=[action])



class MonitoredLog(object):

    def __init__(self, log_file, position=0, actions=[]):
        self.actions = actions
        self.log_file = log_file
        self.open_file = None
        self._open_file()

    def reset(self):
        self.close()
        self._open_file()

    def notify_change(self):
        pos = self.open_file.tell()
        line = self.open_file.readline()
        while line != '':
            if line[-1:] == '\n':
                for action in self.actions:
                    action(line[:-1])
                pos = self.open_file.tell()
                line = self.open_file.readline()
            else:
                # if we get a partial line we seek back to the start of the line
                self.open_file.seek(pos)
                line = ''

    def _open_file(self):
        if os.path.isfile(self.log_file):
            self.open_file = open(self.log_file, 'r')

    def close(self):
        if self.open_file is not None:
            self.open_file.close()
        self.open_file = None


handler = EventHandler()
handler.register_filter("./foo/bar", lambda line: print("./foo/bar line: %s" % line))

wm = pyinotify.WatchManager()
wm.add_watch('./foo', pyinotify.ALL_EVENTS, rec=True)

notifier = pyinotify.Notifier(wm, handler)
notifier.loop()




"""
<Event dir=True mask=0x40000020 maskname=IN_OPEN|IN_ISDIR name='' path=foo pathname=/home/philip/LogBan/foo wd=1 >
<Event dir=True mask=0x40000001 maskname=IN_ACCESS|IN_ISDIR name='' path=foo pathname=/home/philip/LogBan/foo wd=1 >
<Event dir=True mask=0x40000010 maskname=IN_CLOSE_NOWRITE|IN_ISDIR name='' path=foo pathname=/home/philip/LogBan/foo wd=1 >
<Event dir=True mask=0x40000020 maskname=IN_OPEN|IN_ISDIR name='' path=foo pathname=/home/philip/LogBan/foo wd=1 >
<Event dir=True mask=0x40000001 maskname=IN_ACCESS|IN_ISDIR name='' path=foo pathname=/home/philip/LogBan/foo wd=1 >
<Event dir=True mask=0x40000001 maskname=IN_ACCESS|IN_ISDIR name='' path=foo pathname=/home/philip/LogBan/foo wd=1 >
<Event dir=True mask=0x40000020 maskname=IN_OPEN|IN_ISDIR name=bar path=foo pathname=/home/philip/LogBan/foo/bar wd=1 >
<Event dir=True mask=0x40000020 maskname=IN_OPEN|IN_ISDIR name='' path=foo/bar pathname=/home/philip/LogBan/foo/bar wd=2 >
<Event dir=True mask=0x40000001 maskname=IN_ACCESS|IN_ISDIR name=bar path=foo pathname=/home/philip/LogBan/foo/bar wd=1 >
<Event dir=True mask=0x40000001 maskname=IN_ACCESS|IN_ISDIR name='' path=foo/bar pathname=/home/philip/LogBan/foo/bar wd=2 >
<Event dir=True mask=0x40000010 maskname=IN_CLOSE_NOWRITE|IN_ISDIR name=bar path=foo pathname=/home/philip/LogBan/foo/bar wd=1 >
<Event dir=True mask=0x40000010 maskname=IN_CLOSE_NOWRITE|IN_ISDIR name='' path=foo/bar pathname=/home/philip/LogBan/foo/bar wd=2 >
<Event dir=True mask=0x40000020 maskname=IN_OPEN|IN_ISDIR name=bar path=foo pathname=/home/philip/LogBan/foo/bar wd=1 >
<Event dir=True mask=0x40000020 maskname=IN_OPEN|IN_ISDIR name='' path=foo/bar pathname=/home/philip/LogBan/foo/bar wd=2 >
<Event dir=True mask=0x40000001 maskname=IN_ACCESS|IN_ISDIR name=bar path=foo pathname=/home/philip/LogBan/foo/bar wd=1 >
<Event dir=True mask=0x40000001 maskname=IN_ACCESS|IN_ISDIR name='' path=foo/bar pathname=/home/philip/LogBan/foo/bar wd=2 >
<Event dir=True mask=0x40000001 maskname=IN_ACCESS|IN_ISDIR name=bar path=foo pathname=/home/philip/LogBan/foo/bar wd=1 >
<Event dir=True mask=0x40000001 maskname=IN_ACCESS|IN_ISDIR name='' path=foo/bar pathname=/home/philip/LogBan/foo/bar wd=2 >
<Event dir=False mask=0x200 maskname=IN_DELETE name=baz path=foo/bar pathname=/home/philip/LogBan/foo/bar/baz wd=2 >
<Event dir=True mask=0x40000010 maskname=IN_CLOSE_NOWRITE|IN_ISDIR name=bar path=foo pathname=/home/philip/LogBan/foo/bar wd=1 >
<Event dir=True mask=0x40000010 maskname=IN_CLOSE_NOWRITE|IN_ISDIR name='' path=foo/bar pathname=/home/philip/LogBan/foo/bar wd=2 >
<Event dir=True mask=0x400 maskname=IN_DELETE_SELF name='' path=foo/bar pathname=/home/philip/LogBan/foo/bar wd=2 >
<Event dir=False mask=0x8000 maskname=IN_IGNORED name='' path=foo/bar pathname=/home/philip/LogBan/foo/bar wd=2 >
<Event dir=True mask=0x40000200 maskname=IN_DELETE|IN_ISDIR name=bar path=foo pathname=/home/philip/LogBan/foo/bar wd=1 >
<Event dir=False mask=0x200 maskname=IN_DELETE name=bobet path=foo pathname=/home/philip/LogBan/foo/bobet wd=1 >
<Event dir=True mask=0x40000010 maskname=IN_CLOSE_NOWRITE|IN_ISDIR name='' path=foo pathname=/home/philip/LogBan/foo wd=1 >
<Event dir=True mask=0x400 maskname=IN_DELETE_SELF name='' path=foo pathname=/home/philip/LogBan/foo wd=1 >
"""

