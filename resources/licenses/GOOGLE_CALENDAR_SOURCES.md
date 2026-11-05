# Google calendar dependency sources

The Google ICS integration uses unmodified **icalendar 6.3.2** (BSD-2-Clause),
**recurring-ical-events 3.8.2** and **x-wr-timezone 2.0.1** (both LGPL-3.0-or-later).
Their copyright and license texts are in `libraries/` and listed in `manifest.json`.
The LGPL dependencies' official source distributions are bundled in `sources/` and
can be saved through Settings → Program information. Complete GPLv3 and LGPLv3
texts are also available in `pyxlsb/COPYING` and `pyxlsb/COPYING.LESSER`.
The library licenses apply to those libraries, not as a replacement for this app's MIT license.

To use modified versions, obtain the application source from
<https://github.com/ghchoi48/HeartWings>, follow `BUILDING.md`, unpack the bundled
source distributions, modify them, and install the local directories with
`python -m pip install --no-deps --force-reinstall /path/to/modified/library` after
installing the app requirements. Run from source or rebuild with the documented
PyInstaller process. Version pins describe the official baseline and do not
prohibit using modified libraries. Reverse engineering for debugging modifications
to these LGPL libraries is permitted. When redistributing a modified build, update
the bundled corresponding sources, notice versions, and hashes to match it.

`python-dateutil`, `six`, `tzdata`, and `click` are existing dependencies; their
notices are already included in the manifest. The desktop spec explicitly includes
timezone data for offline timezone conversion on Windows.
