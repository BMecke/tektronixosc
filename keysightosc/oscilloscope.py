import visa as vi


def list_connected_devices():
    """List all connected VISA device addresses."""
    rm = vi.ResourceManager()
    resources = rm.list_resources()
    return resources


class Oscilloscope:
    """Interface for a Keysight digital storage oscilloscope."""

    def __init__(self, resource=None):
        """Class constructor. Open the connection to the instrument using the VISA interface.

        Args:
            resource (str): Resource name of the instrument. If not specified, first device
            returned by visa.ResourceManager's list_resources method is used.
        """

        self._resource_manager = vi.ResourceManager()
        if not resource:
            connected_resources = self._resource_manager.list_resources()
            if len(connected_resources) == 0:
                raise RuntimeError('No device connected.')
            else:
                self._instrument = self._resource_manager.open_resource(connected_resources[0])
        else:
            self._instrument = self._resource_manager.open_resource(resource)

    def _err_check(self):
        """Check if instrument for error."""
        answer = self._instrument.query(":SYSTem:ERRor?")
        if not answer.startswith('+0,'):
            raise RuntimeError('Instrument error: {}.'.format(answer.split('"')[1]))

    def _write(self, message):
        """Write a message to the visa interface and check for errors."""
        self._instrument.write(message)
        self._err_check()

    def _query(self, message):
        """Send a query to the visa interface and check for errors."""
        answer = self._instrument.query(message)
        self._err_check()
        return answer

    def _query_binary(self, message):
        """Send a query for binary values."""
        answer = self._instrument.query_binary_values(message, datatype='s')
        self._err_check()
        return answer

    def reset(self):
        """Reset the instrument to standard settings."""
        self._write('*RST')

    def run(self):
        """Start data acquisition."""
        self._write(':RUN')

    def single(self):
        """Arm for single shot acquisition."""
        self._write(':SINGle')

    def stop(self):
        """Stop acquisition."""
        self._write(':STOP')

    def trigger(self):
        """Manually trigger the instrument."""
        self._write('*TRG')

    def get_signal_raw(self):
        """Get the raw data displayed on screen."""
        data = self._query_binary(':WAVeform:DATA?')
        return list(data[0])

    @property
    def x_range(self):
        """Horizontal range."""
        return float(self._query(':TIMebase:RANGe?'))

    @x_range.setter
    def x_range(self, range_):
        """Set horizontal range.

        Args:
            range_: Horizontal range in seconds.
        """
        self._write(':TIMebase:RANGe {}'.format(str(range_)))

    @property
    def x_offset(self):
        """Offset of the time vector."""
        return float(self._query(':WAVeform:XORigin?'))

    @property
    def x_increment(self):
        """Increment of the time vector."""
        return float(self._query(':WAVeform:XINCrement?'))

    @property
    def y_range(self):
        """Range of each channel in volts."""
        return float(self._query(':CHANnel1:RANGe?')), float(self._query(':CHANnel2:RANGe?'))

    @y_range.setter
    def y_range(self, ranges):
        """Set voltage range for each channel.

        Args:
            ranges: Ranges in volts for each channel if iterable, range for both channels if not.
        """
        if hasattr(ranges, '__iter__'):
            self._write(':CHANnel1:RANGe {}V'.format(str(ranges[0])))
            self._write(':CHANnel2:RANGe {}V'.format(str(ranges[1])))
        else:

            self._write(':CHANnel1:RANGe {}V'.format(str(ranges)))
            self._write(':CHANnel2:RANGe {}V'.format(str(ranges)))

    @property
    def y_adc_zero(self):
        """Zero value of the analog to digital converter."""
        return int(self._query(':WAVeform:YREFerence?'))

    @property
    def y_offset(self):
        """Offset of the measured voltage."""
        return float(self._query(':WAVeform:YORigin?'))

    @property
    def y_increment(self):
        """Increment of the measured voltage."""
        return float(self._query(':WAVeform:YINCrement?'))

    @property
    def waveform_source(self):
        """Selected channel or function."""
        return self._query(':WAVeform:SOURce?').strip()

    @waveform_source.setter
    def waveform_source(self, source):
        """Select channel or function.

        Args:
            source: Either an integer specifying the channel or a string according to the
                instrument interface documentation.
        """
        if source is 1 or source is 2:
            self._write(':WAVeform:SOURce CHANnel{}'.format(str(source)))
        else:
            self._write(':WAVeform:SOURce {}'.format(source))

    @property
    def white_image_bg(self):
        """Image background color."""
        return self._query(':HARDcopy:INKSaver?') == '1\n'

    @white_image_bg.setter
    def white_image_bg(self, value):
        """Set image background color."""
        if value:
            self._write(':HARDcopy:INKSaver 1')
        else:
            self._write(':HARDcopy:INKSaver 0')

    def get_signal(self, source=None):
        """Get the signal displayed on screen.

        Args:
            source: Source of the signal (channel or function).
        """
        if source:
            self.waveform_source = source
        adc_zero = self.y_adc_zero
        increment = self.y_increment
        offset = self.y_offset
        return [(value - adc_zero) * increment + offset for value in self.get_signal_raw()]

    def get_time_vector(self):
        """Get the time vector for the signal displayed on screen."""
        n_samples = len(self.get_signal_raw())
        increment = self.x_increment
        offset = self.x_offset
        return [offset + increment * idx for idx in range(n_samples)]

    def screenshot(self, filename):
        """Save the oscilloscope screen data as image.

        Args:
            filename: Name of the image file to save.
        """
        image_data = self._query_binary(":DISPlay:DATA? PNG, COLor")
        if not filename.endswith('.png'):
            filename += '.png'
        with open(filename, 'wb') as file:
            file.write(image_data[0])
