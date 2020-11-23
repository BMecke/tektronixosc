import visa as vi
import pyvisa


def list_connected_devices():
    """List all connected VISA device addresses."""
    rm = vi.ResourceManager()
    resources = rm.list_resources()
    return resources


class Oscilloscope:
    """Interface for a Keysight digital storage oscilloscope."""

    def __init__(self, resource=None):
        """Class constructor. Open the connection to the instrument using the
        VISA interface.

        Args:
            resource (str): Resource name of the instrument. If not specified,
                            first connected device returned by visa.
                            ResourceManager's list_resources method is used.
        """

        self._resource_manager = vi.ResourceManager()
        if not resource:
            connected_resources = self._resource_manager.list_resources()
            if len(connected_resources) == 0:
                raise RuntimeError('No device connected.')
            else:
                res_num = 0
                while True:
                    try:
                        self._instrument = self._resource_manager.open_resource(connected_resources[res_num])
                        break
                    except pyvisa.errors.VisaIOError:
                        res_num += 1
                        pass
                    except IndexError:
                        raise RuntimeError("no visa device connected")

        else:
            self._instrument = self._resource_manager.open_resource(resource)
        # Set query_delay to 0.2 seconds to transmit data securely.
        # Important for Linux systems, because zero delay causes false data.
        self.visa_query_delay = 0.2
        # Increase timeout to 10 seconds for transfer of long signals.
        self.visa_timeout = 10

        self.channels = [Channel(self, 1), Channel(self, 2)]

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

    @property
    def visa_query_delay(self):
        """Visa interface query_delay in seconds."""
        return self._instrument.query_delay

    @visa_query_delay.setter
    def visa_query_delay(self, query_delay):
        """Set visa interface query_delay.

        Args:
            query_delay: Interface query_delay in seconds.
        """
        self._instrument.query_delay = query_delay

    @property
    def visa_timeout(self):
        """Visa interface timeout in seconds."""
        return self._instrument.timeout / 1000

    @visa_timeout.setter
    def visa_timeout(self, timeout):
        """Set visa interface timeout.

        Args:
            timeout: Interface timeout in seconds.
        """
        self._instrument.timeout = timeout * 1000

    def reset(self):
        """Reset the instrument to standard settings.

        Note: Scope standard setting is 10:1 for probe attenuation. Because
              this seems unintuitive, in addition to the reset, the probe
              attenuation is set to 1:1.
        """
        self._write('*RST')
        self.attenuation = 1

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
        """Select the source for the wave form data.

        Args:
            source: Source for the waveform data (CHAN<n>, FUNC, MATH, FFT,
                    WMEM<r>, ABUS, EXT).
        """
        self._write(':WAVeform:SOURce {}'.format(source))

    @property
    def waveform_points_mode(self):
        """Selected record mode."""
        return self._query(':WAVeform:POINts:MODE?')

    @waveform_points_mode.setter
    def waveform_points_mode(self, mode):
        """Select record mode.

        Args:
            mode: A string specifying the mode ('NORM', 'MAX' or 'RAW').
        """
        self._write(':WAVeform:POINts:MODE {}'.format(mode))

    @property
    def waveform_points(self):
        """Number of points to be transferred in the selected record mode."""
        return self._query(':WAVeform:POINts?')

    @waveform_points.setter
    def waveform_points(self, num):
        """Select number of points to be transferred in the selected record
        mode. If mode is 'MAX' the number of points will be set for the
        'RAW' mode.

        Args:
            num: The number of points to be transferred.
        """
        if (self.waveform_points_mode == 'RAW\n') or (self.waveform_points_mode == 'MAX\n'):
            self.stop()
        self._write(':WAVeform:POINts {}'.format(num))

    @property
    def fft_type(self):
        """Selected FFT vertical units."""
        return self._query(':FFT:VTYPe?').strip()

    @fft_type.setter
    def fft_type(self, type_fft):
        """Select FFT vertical units.

        Args:
            type_fft: current FFT vertical units ('DEC' or 'VRMS').
        """
        self._write(':FFT:VTYPe {}'.format(type_fft))

    @property
    def fft_source(self):
        """Selected FFT source."""
        return self._query(':FFT:SOURce1?').strip()

    @fft_source.setter
    def fft_source(self, source):
        """Select FFT source.

        Args:
            source: channel source for the FFT.
        """
        self._write(':FFT:SOURce1 CHAN{}'.format(source))

    @property
    def fft_window(self):
        """Selected FFT window."""
        return self._query(':FFT:WINDow?').strip()

    @fft_window.setter
    def fft_window(self, window):
        """Select FFT window.

        Args:
            window: window for the FFT ('RECT', 'HANN', 'FLAT' or 'BHAR').
        """
        self._write(':FFT:WINDow {}'.format(window))

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

    def get_time_vector(self, source=None):
        """Get the time vector for the signal displayed on screen.

        Args:
            source: Source of the signal (channel or function).
        """
        if source:
            self.waveform_source = source
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


class Channel:
    """Channel class for the Oscilloscope."""
    def __init__(self, osc, number):
        self.number = number
        self.osc = osc

    def _write(self, message):
        """Write a message to the visa interface and check for errors."""
        self.osc._write(message)

    def _query(self, message):
        """Send a query to the visa interface and check for errors."""
        value = self.osc._query(message)
        return value

    @property
    def y_range(self):
        """Range of the channel in volts."""
        return float(self._query(':CHANnel{}:RANGe?'.format(self.number)))

    @y_range.setter
    def y_range(self, range_):
        """Set voltage range for each channel.

        Args:
            range_: Range in volts.
        """
        self._write(':CHANnel{}:RANGe {}V'.format(self.number, range_))

    @property
    def y_range_per_interval(self):
        """Range per interval in volts."""
        return self.y_range/8

    @y_range_per_interval.setter
    def y_range_per_interval(self, range_):
        """Set voltage range per interval.

        Args:
            range_: Ranges per interval in volts.
        """
        self.y_range = range_*8

    @property
    def attenuation(self):
        """Probe attenuation."""
        return float(self._query(':CHANnel{}:PROBe?'.format(self.number)))

    @attenuation.setter
    def attenuation(self, att):
        """Set probe attenuation range for each channel.

        Args:
            att: Attenuation to set.
        """
        self._write(':CHANnel{}:PROBe {}'.format(self.number, att))

    @property
    def measured_unit(self):
        """Get the measurement unit of the probe."""
        return self._query(':CHANnel{}:UNITs?'.format(self.number)).replace("\n", "")

    @measured_unit.setter
    def measured_unit(self, unit):
        """Set the measurement unit of the probe.

        Args:
            unit: Unit to set. Either "VOLT" or "AMP".
        """
        self._write(':CHANnel{}:UNITs {}'.format(self.number, unit))

    def set_as_waveform_source(self):
        """Set the channel as source for acquiring waveform data."""
        self._write(':WAVeform:SOURce CHANnel{}'.format(self.number))

    def set_as_fft_source(self):
        """Set the channel as source for the fft."""
        self.osc.fft_source(self.number)
