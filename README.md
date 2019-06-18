# LogBan

**The first major release of Logban is planned for early May 2019.**

Logban is intended as a replacement for [fail2ban][1].  This tool is still very new and no-where near as tested or comprehensive as fail2ban.  The aimed improvements are:

 - Simpler configuration
 - Lower memory consumption
 - Simple plugin architecture to remove the need for complex config

## Installing
### Installing from a package - *Debian, Ubuntu and Mint*

Logban has been packaged for Debian Linux and should be compatible with Ubuntu and Mint.  Installing on any of these systems the `.deb` file can be downloaded from the [releases][3] page.  To install it (as root) download the file and then:

    apt-get install ./couling-logban_1.0_all.deb

### Installing from source

Install a source from the `release` branch.  Do not install `master` on a live system.  No compiling is required.  Simply clone from git and use symlinks to put things in the right place.  For example if you want to clone to `/opt/Logban` then as root:

    # Install dependencies
    apt-get install python3, python3-configobj, python3-pyinotify, python3-sqlalchemy

    # Clone and checkout the code
    cd /opt
    git clone https://github.com/couling/LogBan.git
    cd LogBan
    git checkout master

    # Wire Logban into your system
    ln -s /opt/Logban/logban.py                /usr/sbin/logban
    ln -s /opt/Logban/logban                   /usr/lib/python3/dist-packages/logban
    ln -s /opt/Logban/package/config           /etc/Logban    
    ln -s /opt/Logban/package/systemd.service  /lib/systemd/system/logban.service
    ln -s /opt/Logban/package/logrotate.conf   /etc/logrotate.d/logban

## Building packages

Packages are built using Philip Coulings [`package-project`][2] tool.  Version numbers will be automatically determined using git tags.

    package-project package/manifest


## Contributing

Please feel free to raise issues and submit pull requests.  All contributions are welcome.  At this time Logban is maintained by a team of one: Philip Couling.

Contributions are particularly welcome for:

 - Filters for applications
 - New complex triggers to support applications
 - Plugins for monitoring other log types (eg: network monitoring)
 - Output plugins (eg: email)

Please see [docs/plugins.md](./docs/plugins.md) for technical informaiton.

## License

This software is released under the MIT license, see [LICENSE.md](./LICENCE.md).

 [1]: https://www.fail2ban.org/wiki/index.php/Main_Page
 [2]: https://github.com/couling/DPKG-Build-Tools
 [3]: https://github.com/couling/LogBan/releases
