import visa as vi
import pyvisa
import numpy as np


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
        """Select the source for the waveform data.

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
    def math_function(self):
        """Selected math function."""
        return self._query(":FUNC:OPERation?").strip()

    @math_function.setter
    def math_function(self, ftype):
        """Select the current math_function.

         Args:
             ftype (str): Current function ('ADD', 'SUBT', 'MULT', 'DIV',
                          'FFT', 'FFTPhase', 'LOWPass').
        """
        self._write(":FUNC:OPERation {}".format(ftype))

    @property
    def math_lowpass_freq(self):
        """Get the -3dB cutoff frequency in Hz for the math_function
        "LOWPass".
        """
        return float(self._query("FUNCtion:FREQuency:LOWPass?"))

    @math_lowpass_freq.setter
    def math_lowpass_freq(self, frequency):
        """Set the -3dB cutoff frequency in Hz for the math_function "LOWPass".

        Args:
            frequency: Frequency to set the cutoff frequency.
        """
        self._write("FUNCtion:FREQuency:LOWPass {}".format(frequency))

    @property
    def math_fft_ordinate_unit(self):
        """Selected unit for the ordinate of the FFT operations.

        If the the math_function is set to 'FFTPhase' the ordinate unit
        of that operation is returned.

        Else the 'FFT' ordinate unit is returned.
        """
        return self._query(':FUNCtion:FFT:VTYPe?').strip()

    @math_fft_ordinate_unit.setter
    def math_fft_ordinate_unit(self, fft_unit):
        """Select the vertical unit for the FFT operations.

        Args:
            fft_unit: Current FFT vertical unit. 'RAD' or 'DEGR' when
                      math_function is set to 'FFTPhase'. 'DEC' or 'VRMS' for
                      the 'FFT' (Current math_function does not have to be
                      'FFT').
        """
        self._write(':FUNCtion:FFT:VTYPe {}'.format(fft_unit))

    @property
    def math_fft_window(self):
        """Selected FFT window. This option is applied on the 'FFT' as well
         as the 'FFTPhase' math_function.
        """
        return self._query(':FUNCtion:FFT:WINDow?').strip()

    @math_fft_window.setter
    def math_fft_window(self, window):
        """Select FFT window. This option is applied on the 'FFT' as well
         as the 'FFTPhase' math_function.

        Args:
            window: Window for the FFT ('RECT', 'HANN', 'FLAT' or 'BHAR').
        """
        self._write('FUNCtion:FFT:WINDow {}'.format(window))

    @property
    def math_fft_center_freq(self):
        """Get the center frequency of the FFT. This option is applied on
        the 'FFT' as well as the 'FFTPhase' math_function.
        """
        return float(self._query(":FUNCtion:FFT:CENTer?").strip())

    @math_fft_center_freq.setter
    def math_fft_center_freq(self, frequency):
        """Set the center frequency of the FFT in Hz. This option is
        applied on the 'FFT' as well as the 'FFTPhase' math_function.

        Args:
            frequency (int): Center frequency of the FFT in Hz.
        """
        self._write(":FUNCtion:FFT:CENTer {}".format(frequency))

    @property
    def math_fft_span_freq(self):
        """Get the frequency span of the FFT in Hz. This option is
        applied on the 'FFT' as well as the 'FFTPhase' math_function.
        """
        return float(self._query(":FUNCtion:FFT:SPAN?").strip())

    @math_fft_span_freq.setter
    def math_fft_span_freq(self, frequency):
        """Set the frequency span of the FFT in Hz. This option is
        applied on the 'FFT' as well as the 'FFTPhase' math_function.

        Args:
            frequency (int): Span frequency of the FFT in Hz.
        """
        self._write(":FUNCtion:FFT:SPAN {}".format(frequency))

    @property
    def math_function_offset(self):
        """Get the offset of the current math_function.

        For the math_functions 'ADD', 'SUBT', 'MULT', 'DIV' and 'LOWPass' the
        offset is given in V.

        For the math_function 'FFT' the offset is given in dBV or in V
        depending on the current fft_ordinate_unit.

        For the math_function 'FFTPhase' the offset is given in radiant or
        degrees depending on the current fft_ordinate_unit.
        """
        return float(self._query(":FUNCtion:OFFSet?").strip())

    @math_function_offset.setter
    def math_function_offset(self, offset):
        """Set offset of the current math_function.

        For the math_functions 'ADD', 'SUBT', 'MULT', 'DIV' and 'LOWPass' the
        offset is set in V.

        For the math_function 'FFT' the offset is set in dBV or in V depending
        on the current fft_ordinate_unit.

        For the math_function 'FFTPhase' the offset is set in radiant or
        degrees depending on the current fft_ordinate_unit.

        Args:
            offset (float): Offset value to set.
        """
        self._write(":FUNCtion:OFFSet {}".format(offset))

    @property
    def math_function_scale(self):
        """Get the scale of the current math_function.

        For the math_functions 'ADD', 'SUBT', 'MULT', 'DIV' and 'LOWPass' the
        scale is given in V.

        For the math_function 'FFT' the scale is given in dB or in V depending
        on the current fft_ordinate_unit.

        For the math_function 'FFTPhase' the scale is given in radiant or
        degrees depending on the current fft_ordinate_unit.
        """
        return float(self._query(":FUNCtion:SCALe?").strip())

    @math_function_scale.setter
    def math_function_scale(self, scale):
        """Set the scale of the current math_function.

        For the math_functions 'ADD', 'SUBT', 'MULT', 'DIV' and 'LOWPass' the
        scale is set in V.

        For the math_function 'FFT' the scale is set in dB or in V depending on
        the current fft_ordinate_unit.

        For the math_function 'FFTPhase' the scale is given in radiant or
        degrees depending on the current fft_ordinate_unit.
        """
        self._write(":FUNCtion:SCALe {}".format(scale))

    def get_math_function_source(self, source):
        """Get a function source. There are two sources
        (source 1 and source 2). These sources are used for the
        math_functions and can be either channel 1 or channel 2.

        Args:
            source(int): Source to get.
        """
        return self._query(":FUNCtion:SOURce{}?".format(source)).strip()

    def set_math_function_source(self, source, channel):
        """Set a math source. There are two sources (source 1 and source 2).
        These sources are used for the math_functions and can be channel 1 or
        channel 2. The math_functions 'ADD', 'SUBT', 'MULT' and 'DIV' use
        source 1 and source 2. The math_functions 'FFT', 'FFTPhase', and
        'LOWPass' use only source 1.

        Args:
            source: Source to set.
            channel: Channel to set the source to.
        """
        self._write(":FUNCtion:SOURce{} CHANnel{}".format(source, channel))

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
            source: Source for the waveform data (CHAN<n>, FUNC, MATH, FFT,
                    WMEM<r>, ABUS, EXT).
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
            source: Source for the waveform data (CHAN<n>, FUNC, MATH, FFT,
                    WMEM<r>, ABUS, EXT).
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

    def save_setup(self, index):
        """Save the current setup on the internal oscilloscope memory.

        Args:
            index (int): Index of the setup file (0-9).
        """
        self._write(':SAVE:SETup {}'.format(index))

    def load_setup(self, index):
        """Load a setup from the internal oscilloscope memory.

        Args:
            index (int): Index of the setup file (0-9).
        """
        self._write(":RECall:SETup {}".format(index))


class Channel:
    """Channel class for the Oscilloscope."""
    def __init__(self, osc, channel_index):
        self.channel_index = channel_index
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
        return float(self._query(':CHANnel{}:RANGe?'.format(self.channel_index)))

    @y_range.setter
    def y_range(self, range_):
        """Set voltage range for each channel.

        Args:
            range_: Range in volts.
        """
        self._write(':CHANnel{}:RANGe {}V'.format(self.channel_index, range_))

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
        return float(self._query(':CHANnel{}:PROBe?'.format(self.channel_index)))

    @attenuation.setter
    def attenuation(self, att):
        """Set probe attenuation range for each channel.

        Args:
            att: Attenuation to set.
        """
        self._write(':CHANnel{}:PROBe {}'.format(self.channel_index, att))

    @property
    def measured_unit(self):
        """Get the measurement unit of the probe."""
        return self._query(':CHANnel{}:UNITs?'.format(self.channel_index)).replace("\n", "")

    @measured_unit.setter
    def measured_unit(self, unit):
        """Set the measurement unit of the probe.

        Args:
            unit: Unit to set. Either "VOLT" or "AMP".
        """
        self._write(':CHANnel{}:UNITs {}'.format(self.channel_index, unit))

    def get_signal(self):
        """Get the signal of the channel."""
        self.osc.get_signal("CHAN{}".format(self.channel_index))

    def get_time_vector(self):
        """Get the time vector of the current channel signal."""
        self.osc.get_time_vector("CHAN{}".format(self.channel_index))

    def get_math_fft(self):
        """Get the math FFT of the channel calculated by the oscilloscope.
        Has no DC component. This modifies the current math_function.
        """
        self.osc.func_type = "FFT"
        return self.osc.get_signal("FUNC")

    def get_math_frequency_vector(self):
        """Get the frequency vector of the math FFT."""
        center_freq = self.osc.math_fft_center_freq
        span_freq = self.osc.math_fft_span_freq
        sample_size = self.osc.waveform_points
        frequency_vector = np.linspace(-span_freq/2+center_freq,
                                       center_freq+span_freq/2, sample_size)
        return frequency_vector
