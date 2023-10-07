*********
Changelog
*********

This project follows the guidelines of `Keep a changelog`_ and adheres to
`Semantic versioning`_.

.. _Keep a changelog: http://keepachangelog.com/
.. _Semantic versioning: https://semver.org/

`0.1.1`_ - 2023-10-07
=====================

Added
-----
* Functions to get and set the horizontal scale, record length and presample time.
* Functions to get and set the sample rate (calculated from the horizontal scale).
* Functions to get and set the presample ratio (calculated from the presample time).

Changed
-------
* Changed visa command in x_increment function.
* _data_stop variable is now set to the record length in the constructor.
* Changed url in setup.py to github project website.

.. _0.1.1: https://github.com/bmecke/tektronixosc/releases/tag/0.1.1

`0.1.0`_ - 2023-08-01
=====================

Added
-----
* Files from keysightosc library.
* Some functions described in the tektronix visa command guide.

Changed
-------
* Updated all keysightosc functions to work with tektronix devices.

.. _0.1.0: https://github.com/bmecke/tektronixosc/releases/tag/0.1.0
