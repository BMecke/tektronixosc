import pyvisa as vi
import numpy as np


def list_connected_devices():
    """List all connected VISA device addresses."""
    rm = vi.ResourceManager()
    resources = rm.list_resources()
    return resources


def get_device_id(resource):
    """
    Get the Identification Number of the specified resource.

    Args:
        resource (str): The resource from which to get the IDN.

    Returns:
        dict[str, str]: The 'Manufacturer', 'Model' and 'Serial Number'.
    """
    try:
        rm = vi.ResourceManager()
        device = rm.open_resource(resource)
        idn = device.query('*IDN?')
        parts = idn.split(',')
        return {'Manufacturer': parts[0], 'Model': parts[1], 'Serial Number': parts[2]}

    except (vi.errors.VisaIOError, ValueError):
        return None


def list_connected_keysight_oscilloscopes():
    """List all connected oscilloscopes from keysight technologies."""
    resource_list = list_connected_devices()
    device_list = []
    for res_num in range(len(resource_list)):
        parts = resource_list[res_num].split('::')
        # Keysight manufacturer ID: 10893, Keysight model code for DSOX1102A: 6023
        if len(parts) > 3 and 'USB' in parts[0] and parts[1] == '10893' and parts[2] == '6023':
            device = get_device_id(resource_list[res_num])
            if device is not None:
                device_list.append(device)

    return device_list


class Oscilloscope:
    """Interface for a Keysight digital storage oscilloscope."""

    def __init__(self, resource=None):
        """Class constructor. Open the connection to the instrument using the
        VISA interface.

        Args:
            resource (str): Resource name of the instrument or product ID.
                            If not specified, first connected device returned by visa.
                            ResourceManager's list_resources method is used.
        """

        # find the resource or set it to None, if the instr_id is not in the list
        self._resource_manager = vi.ResourceManager()
        resource_list = self._resource_manager.list_resources()
        visa_name = next((item for item in resource_list
                          if item == resource or ('USB' in item and item.split('::')[3]) == resource), None)

        if visa_name is not None:
            self._instrument = self._resource_manager.open_resource(visa_name)
        else:
            connected = False
            for res_num in range(len(resource_list)):
                parts = resource_list[res_num].split('::')
                # Keysight manufacturer ID: 10893, Keysight model code for DSOX1102A: 6023
                if len(parts) > 3 and 'USB' in parts[0] and parts[1] == '10893' and parts[2] == '6023':
                    try:
                        self._instrument = self._resource_manager.open_resource(resource_list[res_num])
                        connected = True
                        break
                    except vi.errors.VisaIOError:
                        pass
            if not connected:
                raise RuntimeError("No visa device connected")

        # Clear device to prevent "Query INTERRUPTED" errors when the device was plugged off before
        self._clear()

        # Set query_delay to 0.2 seconds to transmit data securely.
        # Important for Linux systems, because zero delay causes false data.
        self.visa_query_delay = 0.2
        # Increase timeout to 10 seconds for transfer of long signals.
        self.visa_timeout = 10

        self.channels = [Channel(self, 1), Channel(self, 2)]

    def _clear(self):
        """
        Clears the status and the error queue.

        The *CLS common command clears the status data structures, the device-defined error queue,
        and the Request-for-OPC flag.
        """
        self._instrument.write('*CLS')

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

    def _acquire_points(self):
        """
        Get the number of data points that the hardware will acquire from the input signal.

        The number of points acquired is not directly controllable. To set the number of points
        to be transferred from the oscilloscope, use the command :WAVeform:POINts.
        The :WAVeform:POINts? query will return the number of points available to be transferred from the oscilloscope.

        Returns:
             int: Number of data points
        """
        return int(self._query(':ACQuire:POINts?').strip())

    @property
    def _identification_number(self):
        """
        Get the instrument type and software version.

        Returns:
            str: The IDN in the following format: <manufacturer_string>,<model>,<serial_number>,<software_revision>
        """
        return self._query('*IDN?')

    @property
    def device_model(self):
        """
        Get the device model.

        Returns:
            str: The device model
        """
        return self._identification_number.split(',')[1]

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
        self.channels[0].attenuation = 1
        self.channels[1].attenuation = 1

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
        return list(data)

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
        """
        Get the data record to be transferred with the :WAVeform:DATA? query.

        For the analog sources, there are two different records that can be transferred:
            • The first is the raw acquisition record. The maximum number of points available
            in this record is returned by the :ACQuire:POINts? query. The raw acquisition
            record can only be transferred when the oscilloscope is not running and can
            only be retrieved from the analog sources.

            • The second is referred to as the measurement record and is a 62,500-point
            (maximum) representation of the raw acquisition record. The measurement
            record can be retrieved from any source.

        Returns:
            str: The points mode ('NORM', 'MAX' or 'RAW').
        """
        return self._query(':WAVeform:POINts:MODE?')

    @waveform_points_mode.setter
    def waveform_points_mode(self, mode):
        """
        Set the data record to be transferred with the :WAVeform:DATA? query.

        For the analog sources, there are two different records that can be transferred:
            • The first is the raw acquisition record. The maximum number of points available
            in this record is returned by the :ACQuire:POINts? query. The raw acquisition
            record can only be transferred when the oscilloscope is not running and can
            only be retrieved from the analog sources.

            • The second is referred to as the measurement record and is a 62,500-point
            (maximum) representation of the raw acquisition record. The measurement
            record can be retrieved from any source.

        Args:
            mode: A string specifying the mode ('NORM', 'MAX' or 'RAW').
        """
        self._write(':WAVeform:POINts:MODE {}'.format(mode))

    @property
    def waveform_points(self):
        """Number of points to be transferred in the selected record mode."""
        return int(self._query(':WAVeform:POINts?').strip())

    @waveform_points.setter
    def waveform_points(self, num):
        """Select number of points to be transferred in the selected record
        mode. If mode is 'MAX' the number of points will be set for the
        'RAW' mode.

        Args:
            num (int): The number of points to be transferred.
        """
        if (self.waveform_points_mode == 'RAW\n') or (self.waveform_points_mode == 'MAX\n'):
            self.stop()
        if self.waveform_count_max < num:
            num = self.waveform_count_max
        self._write(':WAVeform:POINts {}'.format(num))

    @property
    def waveform_count_max(self):
        """
        Get the maximum number of points to be transferred in the selected record mode.

        If the device is set to raw acquisition record, the maximum number of points is returned
        by the :ACQuire:POINts? query. If the device is set to measurement record, the maximum
        number of points is 62,500.

        Returns:
            int: Maximum number of waveform points.
        """

        if self.waveform_points_mode == 'NORM\n':
            return 62500
        else:
            return self._acquire_points()

    @property
    def timebase_scale(self):
        """
        Get the horizontal scale.

        The :TIMebase:SCALe command sets the horizontal scale or units per division for the main window.

        Returns:
            float: time/div in seconds.
        """
        return float(self._query(':TIMebase:SCALe?').strip())

    @timebase_scale.setter
    def timebase_scale(self, time_per_div_in_s):
        """
        Set the horizontal scale.

        The :TIMebase:SCALe command sets the horizontal scale or units per division for the main window.

        Args:
            time_per_div_in_s (float): time/div in seconds.
        """
        self._write(':TIMebase:SCALe {}'.format(time_per_div_in_s))

    @property
    def acquire_sample_rate(self):
        """
        Get the current sample rate.

        The :ACQuire:SRATe? query returns the current oscilloscope acquisition sample rate.
        The sample rate is not directly controllable.

        Returns:
            float: the sample rate.
        """
        return float(self._query(':ACQuire:SRATe?').strip())

    @property
    def trig_mode(self):
        """
        Get the current trigger mode.

        If the :TIMebase:MODE is ROLL or XY, the query returns "NONE".

        Returns:
            str: The trigger mode ('EDGE', 'GLIT', 'PATT', 'SHOL', 'TRAN', 'TV' or 'SBUS1').
        """
        return self._query(':TRIGger:MODE?').strip()

    @trig_mode.setter
    def trig_mode(self, trigger_mode):
        """
        Set the current trigger mode.

        Args:
            trigger_mode (str): The trigger mode ('EDGE', 'GLIT', 'PATT', 'SHOL', 'TRAN', 'TV' or 'SBUS1').
        """
        self._write(':TRIGger:MODE {}'.format(trigger_mode))

    @property
    def trig_sweep(self):
        """
        Get the trigger sweep mode.

        When AUTO sweep mode is selected, a baseline is displayed in the absence of a signal.
        If a signal is present but the oscilloscope is not triggered, the unsynchronized signal
        is displayed instead of a baseline. When NORMal sweep mode is selected and no trigger
        is present, the instrument does not sweep, and the data acquired on the previous trigger
        remains on the screen.

        Returns:
            str: The trigger sweep mode ('AUTO' or 'NORM').
        """
        return self._query(':TRIGger:SWEep?').strip()

    @trig_sweep.setter
    def trig_sweep(self, sweep_mode):
        """
        Set the trigger sweep mode.

        When AUTO sweep mode is selected, a baseline is displayed in the absence of a signal.
        If a signal is present but the oscilloscope is not triggered, the unsynchronized signal
        is displayed instead of a baseline. When NORMal sweep mode is selected and no trigger
        is present, the instrument does not sweep, and the data acquired on the previous trigger
        remains on the screen.

        Args:
            sweep_mode (str): The trigger sweep mode ('AUTO' or 'NORM').
        """
        self._write(':TRIGger:SWEep {}'.format(sweep_mode))

    @property
    def trig_slope(self):
        """
        Get the slope of the edge for the trigger.

        The :TRIGger:SLOPe command specifies the slope of the edge for the trigger.
        The SLOPe command is not valid in TV trigger mode. Instead, use :TRIGger:TV:POLarity
        to set the polarity in TV trigger mode.

        Returns:
            str: The trigger slope ('NEG', 'POS', 'EITH', 'ALT').
        """
        return self._query(':TRIGger:SLOPe?').strip()

    @trig_slope.setter
    def trig_slope(self, trig_slope):
        """
        Set the slope of the edge for the trigger.

        The :TRIGger:SLOPe command specifies the slope of the edge for the trigger.
        The SLOPe command is not valid in TV trigger mode. Instead, use :TRIGger:TV:POLarity
        to set the polarity in TV trigger mode.

        Args:
            trig_slope (str): The trigger slope ('NEG', 'POS', 'EITH', 'ALT').
        """
        self._write(':TRIGger:SLOPe {}'.format(trig_slope))

    @property
    def fft_ordinate_unit(self):
        """Selected unit for the ordinate of the FFT operation."""
        return self._query(':FFT:VTYPe?').strip()

    @fft_ordinate_unit.setter
    def fft_ordinate_unit(self, fft_unit):
        """Select the vertical unit for the FFT operations.

        Args:
            fft_unit: Current FFT vertical unit ('DEC' or 'VRMS').
        """
        self._write(':FFT:VTYPe {}'.format(fft_unit))

    @property
    def fft_window(self):
        """Selected FFT window."""
        return self._query(':FFT:WINDow?').strip()

    @fft_window.setter
    def fft_window(self, window):
        """Select FFT window.

        Args:
            window: Window for the FFT ('RECT', 'HANN', 'FLAT' or 'BHAR').
        """
        self._write(':FFT:WINDow {}'.format(window))

    @property
    def fft_center_freq(self):
        """Get the center frequency of the FFT."""
        return float(self._query(":FFT:CENTer?").strip())

    @fft_center_freq.setter
    def fft_center_freq(self, frequency):
        """Set the center frequency of the FFT in Hz.

        Args:
            frequency (int): Center frequency of the FFT in Hz.
        """
        self._write(":FFT:CENTer {}".format(frequency))

    @property
    def fft_span_freq(self):
        """Get the frequency span of the FFT in Hz. """
        return float(self._query(":FFT:SPAN?").strip())

    @fft_span_freq.setter
    def fft_span_freq(self, frequency):
        """Set the frequency span of the FFT in Hz.

        Args:
            frequency (int): Span frequency of the FFT in Hz.
        """
        self._write(":FFT:SPAN {}".format(frequency))

    @property
    def fft_offset(self):
        """Get the offset of the FFT in dBV or in V depending on the
        current fft_ordinate_unit."""
        return float(self._query(":FFT:OFFSet?").strip())

    @fft_offset.setter
    def fft_offset(self, offset):
        """Set offset of the FFT in dBV or in V depending on the current
        fft_ordinate_unit.

        Args:
            offset (float): Offset value to set.
        """
        self._write(":FFT:OFFSet {}".format(offset))

    @property
    def fft_scale(self):
        """Get the scale of the FFT in dB or in V depending on the current
        fft_ordinate_unit.
        """
        return float(self._query(":FFT:SCALe?").strip())

    @fft_scale.setter
    def fft_scale(self, scale):
        """Set the scale of the FFT in dB or in V depending on the current
        fft_ordinate_unit.

        Args:
            scale (float): Scale value to set.
        """
        self._write(":FFT:SCALe {}".format(scale))

    @property
    def fft_range(self):
        """Get the vertical range of the FFT in dB or in V depending on the
        current fft_ordinate_unit.
        """
        return float(self._query(":FFT:RANGe?").strip())

    @fft_range.setter
    def fft_range(self, range_):
        """Set the range of the FFT in dB or in V depending on the current
        fft_ordinate_unit.

        Args:
            range_ (float): Range value to set.
        """
        self._write(":FFT:RANGe {}".format(range_))

    @property
    def fft_source(self):
        """Get the source of the FFT."""
        return self._query(":FFT:SOURce1?").strip()

    @fft_source.setter
    def fft_source(self, source):
        """Set the source of the FFT.

        Args:
            source (int): Source of the FFT. Either 1 for CHANnel1 or 2 for
                          CHANnel2.
        """
        self._write(":FFT:SOURce1 CHANnel{}".format(source))

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
        """Selected unit for the ordinate of the MATH FFT operations.

        If the the math_function is set to 'FFTPhase' the ordinate unit
        of that operation is returned.

        Else the 'FFT' ordinate unit is returned.
        """
        return self._query(':FUNCtion:FFT:VTYPe?').strip()

    @math_fft_ordinate_unit.setter
    def math_fft_ordinate_unit(self, fft_unit):
        """Select the vertical unit for the MATH FFT operations.

        Args:
            fft_unit: Current FFT vertical unit. 'RAD' or 'DEGR' when
                      math_function is set to 'FFTPhase'. 'DEC' or 'VRMS' for
                      the 'FFT' (Current math_function does not have to be
                      'FFT').
        """
        self._write(':FUNCtion:FFT:VTYPe {}'.format(fft_unit))

    @property
    def math_fft_window(self):
        """Selected MATH FFT window. This option is applied on the 'FFT' as
        well as the 'FFTPhase' math_function.
        """
        return self._query(':FUNCtion:FFT:WINDow?').strip()

    @math_fft_window.setter
    def math_fft_window(self, window):
        """Select MATH FFT window. This option is applied on the 'FFT' as well
         as the 'FFTPhase' math_function.

        Args:
            window: Window for the FFT ('RECT', 'HANN', 'FLAT' or 'BHAR').
        """
        self._write('FUNCtion:FFT:WINDow {}'.format(window))

    @property
    def math_fft_center_freq(self):
        """Get the center frequency of the  MATH FFT. This option is applied on
        the 'FFT' as well as the 'FFTPhase' math_function.
        """
        return float(self._query(":FUNCtion:FFT:CENTer?").strip())

    @math_fft_center_freq.setter
    def math_fft_center_freq(self, frequency):
        """Set the center frequency of the MATH FFT in Hz. This option is
        applied on the 'FFT' as well as the 'FFTPhase' math_function.

        Args:
            frequency (int): Center frequency of the FFT in Hz.
        """
        self._write(":FUNCtion:FFT:CENTer {}".format(frequency))

    @property
    def math_fft_span_freq(self):
        """Get the frequency span of the MATH FFT in Hz. This option is
        applied on the 'FFT' as well as the 'FFTPhase' math_function.
        """
        return float(self._query(":FUNCtion:FFT:SPAN?").strip())

    @math_fft_span_freq.setter
    def math_fft_span_freq(self, frequency):
        """Set the frequency span of the MATH FFT in Hz. This option is
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
        depending on the current math_fft_ordinate_unit.

        For the math_function 'FFTPhase' the offset is given in radiant or
        degrees depending on the current math_fft_ordinate_unit.
        """
        return float(self._query(":FUNCtion:OFFSet?").strip())

    @math_function_offset.setter
    def math_function_offset(self, offset):
        """Set offset of the current math_function.

        For the math_functions 'ADD', 'SUBT', 'MULT', 'DIV' and 'LOWPass' the
        offset is set in V.

        For the math_function 'FFT' the offset is set in dBV or in V depending
        on the current math_fft_ordinate_unit.

        For the math_function 'FFTPhase' the offset is set in radiant or
        degrees depending on the current math_fft_ordinate_unit.

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
        on the current math_fft_ordinate_unit.

        For the math_function 'FFTPhase' the scale is given in radiant or
        degrees depending on the current Math_fft_ordinate_unit.
        """
        return float(self._query(":FUNCtion:SCALe?").strip())

    @math_function_scale.setter
    def math_function_scale(self, scale):
        """Set the scale of the current math_function.

        For the math_functions 'ADD', 'SUBT', 'MULT', 'DIV' and 'LOWPass' the
        scale is set in V.

        For the math_function 'FFT' the scale is set in dB or in V depending on
        the current math_fft_ordinate_unit.

        For the math_function 'FFTPhase' the scale is given in radiant or
        degrees depending on the current math_fft_ordinate_unit.
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
                    WMEM<r>, ABUS, EXT). If set to None the current selected
                    waveform_source is retrieved as signal source.
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
                    WMEM<r>, ABUS, EXT). If set to None the current selected
                    waveform_source is retrieved as signal source
                    for the time vector.
        """
        if source:
            self.waveform_source = source
        n_samples = self.waveform_points
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
            file.write(bytearray(image_data))

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
    def _trig_lvl_low(self):
        """
        Get the low trigger voltage level voltage for the specified source.

        The trigger levels LOW and HIGH are only useful if the trigger mode is set to "Transition mode" (Tran).

        Returns:
            float: The low trigger voltage level.
        """
        return float(self._query(':TRIGger:LEVel:LOW? CHANnel{}'.format(self.channel_index)).replace("\n", ""))

    @_trig_lvl_low.setter
    def _trig_lvl_low(self, trig_lvl):
        """
        Set the low trigger voltage level voltage for the specified source.

        The trigger levels LOW and HIGH are only useful if the trigger mode is set to "Transition mode" (Tran).

        Args:
            trig_lvl (float): The low trigger voltage level.
        """
        self._write(':TRIGger:LEVel:LOW {}, CHANnel{}'.format(trig_lvl, self.channel_index))

    @property
    def _trig_lvl_high(self):
        """
        Get the high trigger voltage level voltage for the specified source.

        The trigger levels LOW and HIGH are only useful if the trigger mode is set to "Transition mode" (Tran).

        Returns:
            float: The high trigger voltage level.
        """
        return float(self._query(':TRIGger:LEVel:HIGH? CHANnel{}'.format(self.channel_index)).replace("\n", ""))

    @_trig_lvl_high.setter
    def _trig_lvl_high(self, trig_lvl):
        """
        Set the high trigger voltage level voltage for the specified source.

        The trigger levels LOW and HIGH are only useful if the trigger mode is set to "Transition mode" (Tran).

        Args:
            trig_lvl (float): The high trigger voltage level.
        """
        self._write(':TRIGger:LEVel:HIGH {}, CHANnel{}'.format(trig_lvl, self.channel_index))

    @property
    def _trig_lvl(self):
        """
        Get the trigger level voltage for the active trigger source.

        The trigger level is only useful if the trigger mode is set to "Edge triggering" (Edge) or
        "Pulse Width triggering" (Glitch).

        Returns:
            float: The edge trigger voltage level.
        """
        return float(self._query(':TRIGger:LEVel? CHANnel{}'.format(self.channel_index)).replace("\n", ""))

    @_trig_lvl.setter
    def _trig_lvl(self, trig_lvl):
        """
        Set the trigger level voltage for the active trigger source.

        The trigger level is only useful if the trigger mode is set to "Edge triggering" (Edge) or
        "Pulse Width triggering" (Glitch).

        Args:
            trig_lvl (float): The edge trigger voltage level.
        """
        self._write(':TRIGger:LEVel {}, CHANnel{}'.format(trig_lvl, self.channel_index))

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
        return self.y_range / 8

    @y_range_per_interval.setter
    def y_range_per_interval(self, range_):
        """Set voltage range per interval.

        Args:
            range_: Ranges per interval in volts.
        """
        self.y_range = range_ * 8

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

    @property
    def coupling(self):
        """
        Get the input coupling for the specified channel.

        Returns:
            str: The coupling for the selected channel ('AC' or 'DC').
        """
        return self._query(':CHANnel{}:COUPling?'.format(self.channel_index)).replace("\n", "")

    @coupling.setter
    def coupling(self, coupling):
        """
        Set the input coupling for the specified channel.

        The coupling for each analog channel can be set to AC or DC.

        Args:
            coupling (str): The coupling for the selected channel ('AC' or 'DC').
        """
        self._write(':CHANnel{}:COUPling {}'.format(self.channel_index, coupling))

    @property
    def trig_lvl(self):
        """
        Get the trigger level.

        Returns:
            list[float]:
                The lower and upper trigger level if the trigger mode is set to "Transition mode" or
                the trigger level if the trigger mode is set to "Edge triggering" or "Pulse Width triggering"
        """
        if self.osc.trig_mode == 'TRAN':
            trig_lvl = [self._trig_lvl_low, self._trig_lvl_high]
        else:
            trig_lvl = [self._trig_lvl]
        return trig_lvl

    @trig_lvl.setter
    def trig_lvl(self, trig_lvl):
        """
        Set the trigger level.

        Args:
            trig_lvl (list[float]):
                The lower and upper trigger level if the trigger mode is set to "Transition mode" or
                the trigger level if the trigger mode is set to "Edge triggering" or "Pulse Width triggering"
        """
        if self.osc.trig_mode == 'TRAN':
            self._trig_lvl_low = min(trig_lvl)
            self._trig_lvl_high = max(trig_lvl)
        else:
            self._trig_lvl = trig_lvl[0]

    @property
    def offset(self):
        """
        Get the vertical channel offset.

        Returns:
            float:
                The current offset value for the selected channel.
        """
        return self._query(':CHANnel{}:OFFSet?'.format(self.channel_index)).replace("\n", "")

    @offset.setter
    def offset(self, offset):
        """
        Set the vertical channel offset.

        Args:
            offset (float):
                The current offset value for the selected channel.
        """
        self._write(':CHANnel{}:OFFSet {}'.format(self.channel_index, offset))

    @property
    def display(self):
        """
        Get  the current display setting for the specified channel (ON=1, OFF=0)

        Returns:
            int:
                1 if the channel is activated or 0 when not.
        """
        return self._query(':CHANnel{}:DISPlay?'.format(self.channel_index)).replace("\n", "")

    @display.setter
    def display(self, value):
        """
        Turn the display of the specified channel on or off
        Args:
            value (int):
                1 (ON) or 0 (OFF)
        """
        self._write(':CHANnel{}:DISPlay {}'.format(self.channel_index, value))

    def get_signal(self):
        """Get the signal of the channel."""
        return self.osc.get_signal("CHAN{}".format(self.channel_index))

    def get_time_vector(self):
        """Get the time vector of the current channel signal."""
        return self.osc.get_time_vector("CHAN{}".format(self.channel_index))

    def get_math_fft(self):
        """Get the MATH FFT of the channel calculated by the oscilloscope.
        Has no DC component. This modifies the current math_function.
        """
        self.osc.func_type = "FFT"
        return self.osc.get_signal("FUNC")

    def get_math_frequency_vector(self):
        """Get the frequency vector of the MATH FFT."""
        center_freq = self.osc.math_fft_center_freq
        span_freq = self.osc.math_fft_span_freq
        sample_size = self.osc.waveform_points
        frequency_vector = np.linspace(-span_freq / 2 + center_freq,
                                       center_freq + span_freq / 2, sample_size)
        return frequency_vector

    def get_fft(self):
        """Get the FFT of the channel calculated by the oscilloscope.
        Has no DC component.
        """
        self.osc.fft_source = str(self.channel_index)
        return self.osc.get_signal("FFT")

    def get_frequency_vector(self):
        """Get the frequency vector of the FFT."""
        center_freq = self.osc.fft_center_freq
        span_freq = self.osc.fft_span_freq
        sample_size = self.osc.waveform_points
        frequency_vector = np.linspace(-span_freq / 2 + center_freq,
                                       center_freq + span_freq / 2,
                                       sample_size)
        return frequency_vector
