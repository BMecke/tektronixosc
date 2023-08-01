**********************
Tektronix Oscilloscope
**********************

Interface for Tektronix Oscilloscopes.


Features
========

* Basic support for model TBS1072C


Installation
============

To install the Tektronix Oscilloscope Interface, run this command in your terminal::

   $ pip install tektronixosc

Note that usage in Windows will require the `NI-VISA driver`_.



Usage
=====

To use Tektronix Oscilloscope in a project::

   from tektronixosc import Oscilloscope

   osc = Oscilloscope()
   # Get signal data from first channel
   data = osc.channels[0].get_signal()


.. _NI-VISA driver: https://www.ni.com/de/support/downloads/drivers/download.ni-visa.html#484351

Thanks
======

Many thanks to the Measurement Engineering Group, since this project is a fork of their project `keysightosc`_.

.. _keysightosc: https://github.com/emtpb/keysightosc