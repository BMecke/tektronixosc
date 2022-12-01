*********************
Keysight Oscilloscope
*********************

Interface for Keysight Oscilloscopes.


Features
========

* Basic support for model DSOX1102A


Installation
============

To install the Keysight Oscilloscope Interface, run this command in your terminal::

   $ pip install keysightosc

Note that usage in Windows will require the `IO Libraries Suite`_ by Keysight.



Usage
=====

To use Keysight Oscilloscope in a project::

   from keysightosc import Oscilloscope

   osc = Oscilloscope()
   # Get signal data from first channel
   data = osc.get_signal('CHAN1')


.. _IO Libraries Suite: https://www.keysight.com/us/en/lib/software-detail/computer-software/io-libraries-suite-downloads-2175637.html
