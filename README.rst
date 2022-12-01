*********************
Keysight Oscilloscope
*********************

Interface for Keysight Oscilloscopes.


Features
========

* Basic support for model DSOX1102A

Usage
=====

To use Keysight Oscilloscope in a project::

   from keysightosc import Oscilloscope

   osc = Oscilloscope()
   # Get signal data from first channel
   data = osc.get_signal('CHAN1')
