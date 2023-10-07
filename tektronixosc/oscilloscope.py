import pyvisa as vi

busy_resources = {}


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
        if resource not in busy_resources:
            rm = vi.ResourceManager()
            device = rm.open_resource(resource)
            idn = device.query('*IDN?')
            parts = idn.split(',')
            resource_info = {'Manufacturer': parts[0], 'Model': parts[1], 'Serial Number': parts[2]}
            busy_resources[resource] = resource_info
            return resource_info
        else:
            return busy_resources[resource]

    except (vi.errors.VisaIOError, ValueError):
        return None


def list_connected_tektronix_oscilloscopes():
    """List all connected oscilloscopes from tektronix technologies."""
    resource_list = list_connected_devices()
    wrong_keys = []
    for key in busy_resources:
        if key not in resource_list:
            wrong_keys.append(key)
    for wrong_key in wrong_keys:
        busy_resources.pop(wrong_key, None)

    device_list = []
    for res_num in range(len(resource_list)):
        parts = resource_list[res_num].split('::')
        # Tektronix manufacturer ID: 1689, Tektronix model code for TBS1072C: 964
        if len(parts) > 3 and 'USB' in parts[0] and (parts[1] == '1689' or parts[1] == '0x699') and \
                (parts[2] == '964' or parts[2] == '0x3C4'):
            device = get_device_id(resource_list[res_num])
            if device is not None:
                device_list.append(device)

    return device_list


class Oscilloscope:
    """Interface for a tektronix digital storage oscilloscope."""

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
        # Tektronix manufacturer id: 1689
        visa_name = next((item for item in resource_list if item == resource or
                          ('USB' in item and item.split('::')[3] == resource and
                           (item.split('::')[1] == '1689' or item.split('::')[1] == '0x699'))), None)

        connected_resource = None
        if visa_name is not None:
            self._instrument = self._resource_manager.open_resource(visa_name)
            connected_resource = visa_name
        else:
            connected = False
            for res_num in range(len(resource_list)):
                parts = resource_list[res_num].split('::')
                # Tektronix manufacturer ID: 1689, Tektronix model code for TBS1072C: 964
                if len(parts) > 3 and 'USB' in parts[0] and (parts[1] == '1689' or parts[1] == '0x699') and \
                        (parts[2] == '964' or parts[2] == '0x3C4'):
                    try:
                        self._instrument = self._resource_manager.open_resource(resource_list[res_num])
                        connected = True
                        connected_resource = resource_list[res_num]
                        break
                    except vi.errors.VisaIOError:
                        pass
            if not connected:
                raise RuntimeError("Could not find any tektronix devices")

        if connected_resource is not None:
            idn = self._instrument.query('*IDN?')
            parts = idn.split(',')
            resource_info = {'Manufacturer': parts[0], 'Model': parts[1], 'Serial Number': parts[2]}
            busy_resources[connected_resource] = resource_info

        # Clear device to prevent "Query INTERRUPTED" errors when the device was plugged off before
        self._clear()

        # Set query_delay to 0.2 seconds to transmit data securely.
        # Important for Linux systems, because zero delay causes false data.
        self.visa_query_delay = 0.2
        # Increase timeout to 10 seconds for transfer of long signals.
        self.visa_timeout = 10

        self.channels = [Channel(self, 1), Channel(self, 2)]

        self._enable_header_in_response = False
        # To transfer waveforms from the instrument to an external controller, follow these steps:
        #    1. Use the DATa:SOUrce command to select the waveform source.
        #    2. Use the DATa:ENCdg command to specify the waveform data format.
        #    3. Use the DATa:WIDth command to specify the number of bytes per data point.
        #    4. Use the DATa:STARt and DATa:STOP commands to specify the part of the waveform that you want to transfer.
        #    5. ...
        self._waveform_encoding = 'BINARY'
        self._binary_data_format = 'SIGNED'
        self._data_width = 1
        # Setting DATa:STARt to 1 and DATa:STOP to 2500 always sends the entire waveform,
        # regardless of the acquisition mode.
        self._data_start = 1
        self._data_stop = self.record_length

    # https://stackoverflow.com/questions/20766813/how-to-convert-signed-to-unsigned-integer-in-python
    @staticmethod
    def _unsigned_to_signed(n, byte_count):
        return int.from_bytes(n.to_bytes(byte_count, 'little', signed=False), 'little', signed=True)

    def _clear(self):
        """
        Clears the status byte and standard event status register and the event queue.

        Command only, no query form. The *CLS command clears the following instrument status data structures:
        • The Event Queue
        • The Standard Event Status Register (SESR)
        • The Status Byte Register (except the MAV bit)
        """
        self._instrument.write('*CLS')

    def _err_check(self):
        """
        Check if instrument for error.

        Raise an RuntimeError if an error is detected.
        """
        answer = self._instrument.query("*ESR?")
        answer = int(answer.removesuffix('\n'))
        if answer != 0:
            raise RuntimeError('Instrument error: Standard Event Status Register code = {0:b}'.format(answer))

    def _query_binary(self, message):
        """Send a query for binary values."""
        answer = self._instrument.query_binary_values(message, datatype='s')
        self._err_check()
        return answer

    def write(self, message):
        """Write a message to the visa interface and check for errors."""
        self._instrument.write(message)
        self._err_check()

    def query(self, message):
        """Send a query to the visa interface and check for errors."""
        answer = self._instrument.query(message)
        answer = answer.removesuffix('\n')
        self._err_check()
        return answer

    def single(self):
        """Arm for single shot acquisition."""
        self.write('ACQuire:STOPAfter SEQuence')

    def continuous(self):
        """Arm for continuous data acquisition."""
        self.write('ACQuire:STOPAfter RUNSTop')

    def stop(self):
        """Stop acquisition."""
        self.write('ACQuire:STATE STOP')

    def reset(self):
        """Reset the instrument to standard settings.

        Note: Scope standard setting is 10:1 for probe attenuation. Because
              this seems unintuitive, in addition to the reset, the probe
              attenuation is set to 1:1.
        """
        self.write('*RST')
        self.channels[0].attenuation = 1
        self.channels[1].attenuation = 1

    def run(self):
        """
        Start data acquisition.

        When State is set to ON or RUN, a new acquisition is started. If the last acquisition was a single acquisition
        sequence, a new single sequence acquisition is started. If the last acquisition was continuous, a new continuous
        acquisition is started.
        If RUN is issued in the middle of completing a single sequence acquisition
        (for example, averaging or enveloping), the acquisition sequence is restarted,
        and any accumulated data is discarded. Also, the instrument resets the number of acquisitions.
        If the RUN argument is issued while in continuous mode, acquisition continues.
        """
        self.write('ACQuire:STATE RUN')

    def autoset(self):
        """
        Causes the instrument to adjust its vertical, horizontal, and trigger controls to display a stable waveform.
        This command is equivalent to pushing the front-panel AUTOSET button. For a detailed description of the Autoset
        function, refer to the user manual for your instrument. Command only, no query form.

        """
        self.write('AUTOSet EXECute')

    def get_signal(self, source=None):
        """
        Get the measured signal.

        To transfer waveforms from the instrument to an external controller, follow these steps:
        (Step 2-4 already done in the init function)
            1. Use the DATa:SOUrce command to select the waveform source.
            2. Use the DATa:ENCdg command to specify the waveform data format.
            3. Use the DATa:WIDth command to specify the number of bytes per data point.
            4. Use the DATa:STARt and DATa:STOP commands to specify the part of the waveform that you want to transfer.
            5. Use the WFMPre? command to transfer waveform preamble information.
            6. Use the CURVe command to transfer waveform data.

        Args:
            source: Source for the waveform data ('CH1', 'CH2', 'MATH', 'REF1', 'REF2').
                    If set to None the current selected waveform_source is retrieved as signal source.
        """
        if source:
            self.data_source = source

        # This command is equivalent to sending both 'WFMOutpre?' and 'CURVe?', with the additional provision that the
        # response to WAVFrm? is guaranteed to provide a synchronized preamble and curve.

        self._enable_header_in_response = True
        self._instrument.write('WAVFrm?')
        data = self._instrument.read_raw()
        self._enable_header_in_response = False

        # Separate 'WFMOutpre?' and 'CURVe?' command
        # 'CURVe?' response format: #<x><yyy><data><newline>,
        # where: <x> is the number of y bytes. For example, if <yyy>=500, then <x>=3.
        curve_start_index = data.find(b'#')
        number_of_bytes = int(chr(data[curve_start_index + 1]))
        curve_length = int(data[curve_start_index + 2: curve_start_index + 2 + number_of_bytes])
        curve_data_start_index = curve_start_index + 2 + number_of_bytes

        header = data[:curve_start_index].decode().split(';')
        y_values = list(data[curve_data_start_index:-1])

        y_values = [self._unsigned_to_signed(value, 1) for value in y_values]
        if len(y_values) != curve_length:
            raise RuntimeError('Error while getting the curve data')

        x_increment = next((s for s in header if 'XINCR' in s), None)
        x_zero = next((s for s in header if 'XZERO' in s), None)
        if not (x_increment or x_zero):
            raise RuntimeError('Error while getting XINCR, XZERO or XOFF')
        x_increment = float(x_increment.split(' ')[1])
        x_zero = float(x_zero.split(' ')[1])
        x_values = [x_zero + index * x_increment for index in range(curve_length)]

        y_increment = next((s for s in header if 'YMULT' in s), None)
        y_zero = next((s for s in header if 'YZERO' in s), None)
        y_off = next((s for s in header if 'YOFF' in s), None)
        if not (y_increment or y_zero or y_off):
            raise RuntimeError('Error while getting YMULT, YZERO or YOFF')
        y_increment = float(y_increment.split(' ')[1])
        y_zero = float(y_zero.split(' ')[1])
        y_off = float(y_off.split(' ')[1])
        y_values = [((y_point - y_off) * y_increment) + y_zero for y_point in y_values]

        return x_values, y_values

    @property
    def _enable_header_in_response(self):
        """
        Queries the Response Header Enable State that causes the to either include or omit headers on query
        responses. This command does not affect IEEE Std 488.2-1987 Common Commands (those starting with an asterisk);
        they never return headers.

        If header is on, the instrument returns command headers as part of the query and formats the query response as
        a valid set command.
        When header is off, the instrument sends back only the values in the response. This format can make it easier to
        parse and extract the information from the response.

        Returns:
            bool: True, if the response header is enabled, false if the response header is disabled.
        """
        state = self.query('HEADer?')
        if state == '1':
            return True
        else:
            return False

    @_enable_header_in_response.setter
    def _enable_header_in_response(self, state):
        """
        Sets the Response Header Enable State that causes the to either include or omit headers on query
        responses. This command does not affect IEEE Std 488.2-1987 Common Commands (those starting with an asterisk);
        they never return headers.

        If header is on, the instrument returns command headers as part of the query and formats the query response as
        a valid set command.
        When header is off, the instrument sends back only the values in the response. This format can make it easier to
        parse and extract the information from the response.

        Args:
            state (bool): True, if the response header is enabled, false if the response header is disabled.
        """
        if state:
            self.write('HEADer ON')
        else:
            self.write('HEADer OFF')

    @property
    def _waveform_encoding(self):
        """
        Queries the type of encoding for outgoing waveform.

        Returns:
            str: The type of encoding for outgoing waveforms ('ASCII', 'BINARY').

                ASCii specifies that the outgoing data is to be in ASCII format.
                Waveforms will be sent as <NR1> numbers.

                BINary specifies that outgoing data is to be in a binary format whose further specification is
                determined by 'WFMOutpre:BYT_Nr', 'WFMOutpre:BIT_Nr', 'WFMOutpre:BN_Fmt' and 'WFMInpre:FILTERFreq'.
        """
        return self.query('WFMOutpre:ENCdg?').upper()

    @_waveform_encoding.setter
    def _waveform_encoding(self, encoding):
        """
         Sets the type of encoding for outgoing waveform.

         Args:
             encoding(str): The type of encoding for outgoing waveforms ('ASCII', 'BINARY').

                ASCii specifies that the outgoing data is to be in ASCII format.
                Waveforms will be sent as <NR1> numbers.

                BINary specifies that outgoing data is to be in a binary format whose further specification is
                determined by 'WFMOutpre:BYT_Nr', 'WFMOutpre:BIT_Nr', 'WFMOutpre:BN_Fmt' and 'WFMInpre:FILTERFreq'.
         """
        if encoding == 'ASCII' or encoding == 'ASCii':
            self.write('WFMOutpre:ENCdg ASCii')
        elif encoding == 'BINARY' or encoding == 'BINary':
            self.write('WFMOutpre:ENCdg BINary')

    @property
    def _data_start(self):
        """
        Queries the starting data point for incoming or outgoing waveform transfer.
        This command lets you transfer partial waveforms to and from the instrument.

        Returns:
            int: The first data point that will be transferred, which ranges from 1 to the record length
        """
        return int(self.query('DATa:STARt?'))

    @_data_start.setter
    def _data_start(self, nr1):
        """
         Sets  the starting data point for incoming or outgoing waveform transfer.
         This command lets you transfer partial waveforms to and from the instrument.

         Args:
             nr1 (int): The first data point that will be transferred, which ranges from 1 to the record length.
         """
        self.write('DATa:STARt {}'.format(str(nr1)))

    @property
    def _data_stop(self):
        """
        Sets or queries the last data point in the waveform that will be transferred when using the CURVe? query.
        This lets you transfer partial waveforms from the instrument Changes to the record length value are not
        automatically reflected in the DATa:STOP value.
        As record length is varied, the DATa:STOP value must be explicitly changed to ensure the entire record
        is transmitted. In other words, curve results will not automatically and correctly reflect increases in record
        length if the distance from DATa:STARt to DATa:STOP stays smaller than the increased record length.
        When using the CURVe command, the instrument stops reading data when there is no more data to read.

        Returns:
            int: The last data point that will be transferred, which ranges from 1 to the record length.
        """
        return int(self.query('DATa:STOP?'))

    @_data_stop.setter
    def _data_stop(self, nr1):
        """
        Sets or queries the last data point in the waveform that will be transferred when using the CURVe? query.
        This lets you transfer partial waveforms from the instrument Changes to the record length value are not
        automatically reflected in the DATa:STOP value.
        As record length is varied, the DATa:STOP value must be explicitly changed to ensure the entire record
        is transmitted. In other words, curve results will not automatically and correctly reflect increases in record
        length if the distance from DATa:STARt to DATa:STOP stays smaller than the increased record length.
        When using the CURVe command, the instrument stops reading data when there is no more data to read.

        If DATa:WIDth is set to 2, the least significant byte is always zero.
        This format is useful for AVErage waveforms.

        Args:
            nr1 (int): The last data point that will be transferred, which ranges from 1 to the record length.
        """
        self.write('DATa:STOP {}'.format(str(nr1)))

    @property
    def _data_width(self):
        """
        Queries the number of bytes per data point in the waveform transferred using the CURVe command.

        Changes to the record length value are not automatically reflected in the DATa:STOP value.
        As record length is varied, the DATa:STOP value must be explicitly changed to ensure the entire record is
        transmitted. In other words, curve results will not automatically and correctly reflect increases in record
        length if the distance from DATa:STARt to DATa:STOP stays smaller than the increased record length.

        Returns:
            int: The number of bytes per waveform data points.
        """
        return int(self.query('DATa:WIDth?'))

    @_data_width.setter
    def _data_width(self, width):
        """
        Queries the number of bytes per data point in the waveform transferred using the CURVe command.

        Changes to the record length value are not automatically reflected in the DATa:STOP value.
        As record length is varied, the DATa:STOP value must be explicitly changed to ensure the entire record is
        transmitted. In other words, curve results will not automatically and correctly reflect increases in record
        length if the distance from DATa:STARt to DATa:STOP stays smaller than the increased record length.

        Args:
            width (int): The number of bytes per waveform data points.
        """
        self.write('DATa:WIDth {}'.format(str(width)))

    @property
    def _binary_data_format(self):
        """
        Returns the format of binary data for outgoing waveforms specified by the DATa:SOUrce command.
        Changing the value of WFMOutpre:BN_Fmt also changes the value of DATa:ENCdg.

        Returns:
            result (str): The format of binary data for outgoing waveforms ('signed', 'unsigned').
        """
        result = self.query('WFMOutpre:BN_Fmt?')
        if result == 'RI':
            return 'signed'
        else:
            return 'unsigned'

    @_binary_data_format.setter
    def _binary_data_format(self, format_of_binary_data):
        """
        Sets the format of binary data for outgoing waveforms specified by the DATa:SOUrce command.
        Changing the value of WFMOutpre:BN_Fmt also changes the value of DATa:ENCdg.

        Args:
            format_of_binary_data (str): The format of binary data for outgoing waveforms ('SIGNED', 'UNSIGNED').
        """
        if format_of_binary_data == 'SIGNED' or format_of_binary_data == 'RI':
            self.write('WFMOutpre:BN_Fmt RI')
        elif format_of_binary_data == 'UNSIGNED' or format_of_binary_data == 'RP':
            self.write('WFMOutpre:BN_Fmt RP')
        else:
            raise ValueError('\'signed\' and \'unsigned\' are the only allowed values in this function')

    @property
    def _identification_number(self):
        """
        The instrument identification code in IEEE 488.2 notation.

        Returns:
            str: The IDN in the following format: TEKTRONIX,<model number>,
                 CF:91.1CT FV:v<instrument firmware version number> TBS 1XXXC:v<module firmware version number>
        """
        return self.query('*IDN?')

    @property
    def device_model(self):
        """
        Get the device model.

        Returns:
            str: The device model
        """
        return self._identification_number.split(',')[1]

    @property
    def max_sample_rate(self):
        """
        The maximum real-time sample rate, which varies from model to model.

        Returns:
            int: The maximum real-time sample rate in samples/second.

        """
        # https://stackoverflow.com/questions/32861429/converting-number-in-scientific-notation-to-int
        max_samplerate = float(self.query('ACQuire:MAXSamplerate?'))
        return int(max_samplerate)

    @property
    def sample_rate(self):
        """
        Get the sample rate.

        Returns:
            float: The sample rate.
        """
        # There are 16 divisions displayed on the screen
        return self.record_length / (self.horizontal_scale * 16)

    @sample_rate.setter
    def sample_rate(self, sample_rate):
        """
        Set the sample rate.

        The value is automatically rounded by the device.

        Args:
            sample_rate (float): The sample rate.
        """
        # There are 16 divisions displayed on the screen
        self.horizontal_scale = self.record_length / (sample_rate * 16)

    @property
    def horizontal_scale(self):
        """
        Queries the time base horizontal scale.

        Returns:
            float: The main scale per division.
        """
        return float(self.query('HORizontal:MAIn:SCAle?'))

    @horizontal_scale.setter
    def horizontal_scale(self, scale):
        """
        Sets the time base horizontal scale.

        Args:
            scale (float): The main scale per division.
        """
        self.write('HORizontal:MAIn:SCAle {}'.format(scale))

    @property
    def acquisition_mode(self):
        """
        Queries the acquisition mode of the instrument for all live waveforms.
        Waveforms are the displayed data point values taken from acquisition intervals.
        Each acquisition interval represents a time duration set by the horizontal scale (time per division).
        The instrument sampling system always samples at the maximum rate,
        so the acquisition interval may include more than one sample.
        The acquisition mode, which you set using this ACQuire:MODe command, determines how the final value of the
        acquisition interval is generated from the many data samples.


        Returns:
            str: The acquisition mode of the instrument for all live waveforms
                 ('SAMPLE', 'PEAKDETECT', 'HIRES', 'AVERAGE')

                SAMple specifies that the displayed data point value is the first sampled value that was taken
                during the acquisition interval. The waveform data has 8 bits of precision in all acquisition modes.
                You can request 16 bit data with a CURVe? query, but the lower-order 8 bits of data will be zero.
                SAMple is the default mode.

                PEAKdetect specifies the display of the high-low range of the samples taken from a single
                waveform acquisition.
                The instrument displays the high-low range as a vertical column that extends from the highest to the
                lowest value sampled during the acquisition interval.
                PEAKdetect mode can reveal the presence of aliasing or narrow spikes.

                HIRes specifies Hi Res mode where the displayed data point value is the average of all the samples taken
                during the acquisition interval. This is a form of averaging, where the average comes from a single
                waveform acquisition. The number of samples taken during the acquisition interval determines the number
                of data values that compose the average.

                AVErage specifies averaging mode, in which the resulting waveform shows an average of SAMple data points
                from several separate waveform acquisitions. The instrument processes the number of waveforms you
                specify into the acquired waveform, creating a running exponential average of the input signal.
                The number of waveform acquisitions that go into making up the average waveform is set or queried using
                the ACQuire:NUMAVg command.
        """
        return self.query('ACQuire:MODe?').upper()

    @acquisition_mode.setter
    def acquisition_mode(self, mode):
        """
        Sets the acquisition mode of the instrument for all live waveforms.
        Waveforms are the displayed data point values taken from acquisition intervals.
        Each acquisition interval represents a time duration set by the horizontal scale (time per division).
        The instrument sampling system always samples at the maximum rate,
        so the acquisition interval may include more than one sample.
        The acquisition mode, which you set using this ACQuire:MODe command, determines how the final value of the
        acquisition interval is generated from the many data samples.

        Args:
            mode (str): The acquisition mode of the instrument for all live waveforms
                  ('SAMPLE', 'PEAKDETECT', 'HIRES', 'AVERAGE')

                SAMple specifies that the displayed data point value is the first sampled value that was taken
                during the acquisition interval. The waveform data has 8 bits of precision in all acquisition modes.
                You can request 16 bit data with a CURVe? query, but the lower-order 8 bits of data will be zero.
                SAMple is the default mode.

                PEAKdetect specifies the display of the high-low range of the samples taken from a single
                waveform acquisition.
                The instrument displays the high-low range as a vertical column that extends from the highest to the
                lowest value sampled during the acquisition interval.
                PEAKdetect mode can reveal the presence of aliasing or narrow spikes.

                HIRes specifies Hi Res mode where the displayed data point value is the average of all the samples taken
                during the acquisition interval. This is a form of averaging, where the average comes from a single
                waveform acquisition. The number of samples taken during the acquisition interval determines the number
                of data values that compose the average.

                AVErage specifies averaging mode, in which the resulting waveform shows an average of SAMple data points
                from several separate waveform acquisitions. The instrument processes the number of waveforms you
                specify into the acquired waveform, creating a running exponential average of the input signal.
                The number of waveform acquisitions that go into making up the average waveform is set or queried using
                the ACQuire:NUMAVg command.
        """
        if mode == 'SAMPLE' or mode == 'SAMple':
            self.write('ACQuire:MODe SAMple')
        elif mode == 'PEAKDETECT' or mode == 'PEAKdetect':
            self.write('ACQuire:MODe PEAKdetect')
        elif mode == 'HIRES' or mode == 'HIRes':
            self.write('ACQuire:MODe HIRes')
        elif mode == 'AVERAGE' or mode == 'AVErage':
            self.write('ACQuire:MODe AVErage')

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

    @property
    def data_source(self):
        """
        Queries which waveform will be transferred from the instrument by the CURVe? query.
        You can transfer only one waveform at a time.

        Returns:
            str: The current data source ('CH1', 'CH2', 'MATH', 'REF1', 'REF2').

                CH1– CH2 specifies which analog channel data will be transferred from the instrument to the controller,
                channels 1 through 2.

                MATH specifies that the math waveform data will be transferred from the instrument to the controller.

                REF1–REF2 specifies which reference waveform data will be transferred from the instrument to the
                controller, waveforms, 1 or 2.
        """
        return self.query('DATa:SOUrce?').split(' ')[1]

    @data_source.setter
    def data_source(self, source):
        """
        Sets which waveform will be transferred from the instrument by the CURVe? query.
        You can transfer only one waveform at a time.

        Args:
            source (str): The current data source ('CH1', 'CH2', 'MATH', 'REF1', 'REF2').

                CH1– CH2 specifies which analog channel data will be transferred from the instrument to the controller,
                channels 1 through 2.

                MATH specifies that the math waveform data will be transferred from the instrument to the controller.

                REF1–REF2 specifies which reference waveform data will be transferred from the instrument to the
                controller, waveforms, 1 or 2.
        """
        self.write('DATa:SOUrce {}'.format(source))

    @property
    def number_of_waveform_points(self):
        """
        Number of points that will be transmitted in response to a CURVe? query.

        Returns:
            int: The number of points for the DATa:SOUrce waveform.
        """
        return int(self.query('WFMOutpre:NR_Pt?'))

    @property
    def record_length(self):
        """
         Returns the horizontal record length of acquired waveforms.
         The sample rate is automatically adjusted at the same time to maintain a constant time per division.

         Returns:
            int: The query form of this command returns the current horizontal record length.
        """
        return int(self.query('HORizontal:RESOlution?'))

    @record_length.setter
    def record_length(self, record_length):
        """
         Sets the horizontal record length of acquired waveforms.
         The sample rate is automatically adjusted at the same time to maintain a constant time per division.

         Args:
            record_length (int): The query form of this command returns the current horizontal record length.
        """
        self._data_stop = record_length
        self.write('HORizontal:RESOlution {}'.format(record_length))

    @property
    def x_increment(self):
        """
        Increment of the time vector. This value corresponds to the sampling interval.

        Returns:
            float: The horizontal point spacing in units of WFMOutpre:XUNit for the waveform specified by the
                   DATa:SOUrce command.
        """
        return float(self.query('WFMOutpre:XINcr?'))

    @property
    def x_unit(self):
        """
        The horizontal units for the waveform.

        Returns:
            str:  The horizontal units for the waveform.
        """
        return self.query('WFMOutpre:XUNit?').upper()

    @property
    def x_offset(self):
        """
        The time coordinate of the first point in the outgoing waveform. This value is in units of WFMOutpre:XUNit?.
        The query command will time out and an error will be generated if the waveform specified by DATa:SOUrce
        is not turned on.

        Returns:
            float: The time coordinate of the first point in the outgoing waveform.
        """
        return float(self.query('WFMOutpre:XZEro?'))

    @property
    def y_increment(self):
        """
        The vertical scale factor per digitizing level in units specified by WFMOutpre:YUNit for the waveform specified
        by the Returns the vertical scale factor per digitizing level in units specified by WFMOutpre:YUNit for the
        waveform specified by the DATa:SOUrce command. The query command will time out and an error is generated if the
        waveform specified by DATa:SOUrce is not turned on. command. The query command will time out and an error is
        generated if the waveform specified by DATa:SOUrce is not turned on.

        Returns:
            float: The vertical scale for the corresponding waveform.
        """
        return float(self.query('WFMOUTPRE:YMULT?'))

    @property
    def y_unit(self):
        """
        The  vertical units for the waveform.

        Returns:
            str:  The  vertical units for the waveform.
        """
        return self.query(' WFMOutpre:YUNit?')

    @property
    def y_offset(self):
        """
        The vertical offset in units specified by WFMOutpre:YUNit? for the waveform specified by the DATa:SOUrce
        command. The query command will time out and an error will be generated if the waveform specified by
        DATa:SOUrce is not turned on.

        Returns:
            float:  The vertical offset in units.
        """
        return float(self.query('WFMOUTPRE:YZERO?'))

    @property
    def trig_source(self):
        """
        Queries the source for the edge trigger. This is equivalent to setting the Source option in the Trigger menu.

        Returns:
            str: The trigger source ('CH1', 'CH2', 'LINE', 'AUX').
        """
        if self.trig_type == 'EDGE':
            return self.query('TRIGger:A:EDGE:SOUrce?').upper()
        elif self.trig_pulse_class == 'RUNT':
            return self.query('TRIGGER:A:RUNT:SOURCE?').upper()
        else:
            return self.query('TRIGger:A:PULse:SOUrce?').upper()

    @trig_source.setter
    def trig_source(self, trigger_source):
        """
        Sets the source for the edge trigger. This is equivalent to setting the Source option in the Trigger menu.

        Args:
            trigger_source (str): The trigger source ('CH1', 'CH2', 'LINE', 'AUX').
        """
        if self.trig_type == 'EDGE':
            self.write('TRIGger:A:EDGE:SOUrce {}'.format(trigger_source))
        elif self.trig_pulse_class == 'RUNT':
            self.write('TRIGger:A:RUNT:SOUrce {}'.format(trigger_source))
        else:
            self.write('TRIGger:A:PULse:SOUrce {}'.format(trigger_source))


    @property
    def trig_type(self):
        """
        Get the current trigger type.
        This is equivalent to setting the Type option in the Trigger menu.

        Returns:
            str: The trigger type ('EDGE', 'PULSE').
        """
        return self.query('TRIGger:A:TYPe?').upper()

    @trig_type.setter
    def trig_type(self, trigger_type):
        """
        Set the current trigger type.
        This is equivalent to setting the Type option in the Trigger menu.

        Args:
            trigger_type (str): The trigger type ('EDGE', 'PULSE').
        """
        if trigger_type == 'EDGE' or trigger_type == 'EDGe':
            self.write('TRIGger:A:TYPe EDGe')
        elif trigger_type == 'PULSE' or trigger_type == 'PULSe':
            self.write('TRIGger:A:TYPe PULSe')

    @property
    def trig_slope(self):
        """
        Get the slope of the edge for the trigger.

        The slope command specifies the slope of the edge for the trigger.
        This is equivalent to setting the slope option in the trigger menu.

        Returns:
            str: The trigger slope ('RISE', 'FALL').
        """
        if self.trig_type == 'EDGE':
            return self.query('TRIGger:A:EDGE:SLOpe?').upper()
        elif self.trig_pulse_class == 'RUNT':
            slope = self.query('TRIGger:A:RUNT:POLarity?').upper()
            if slope == 'NEGATIVE':
                return 'FALL'
            else:
                return 'RISE'
        else:
            slope = self.query('TRIGger:A:PULse:WIDth:POLarity?').upper()
            if slope == 'NEGATIVE':
                return 'FALL'
            else:
                return 'RISE'

    @trig_slope.setter
    def trig_slope(self, trig_slope):
        """
        Set the slope of the edge for the trigger.

        The slope command specifies the slope of the edge for the trigger.
        This is equivalent to setting the slope option in the trigger menu.

        Args:
            trig_slope (str): The trigger slope ('RISE', 'FALL').
        """
        if self.trig_type == 'EDGE':
            if trig_slope == 'RISE' or trig_slope == 'RISe':
                self.write('TRIGger:A:EDGE:SLOpe RISe')
            elif trig_slope == 'FALL':
                self.write('TRIGger:A:EDGE:SLOpe FALL')
        elif self.trig_pulse_class == 'RUNT':
            if trig_slope == 'RISE' or trig_slope == 'RISe':
                self.write('TRIGger:A:RUNT:POLarity POSitive')
            elif trig_slope == 'FALL':
                self.write('TRIGger:A:RUNT:POLarity NEGative')
        else:
            if trig_slope == 'RISE' or trig_slope == 'RISe':
                self.write('TRIGger:A:PULse:WIDth:POLarity POSitive')
            elif trig_slope == 'FALL':
                self.write('TRIGger:A:PULse:WIDth:POLarity NEGative')

    @property
    def pre_sample_time(self):
        """
        Queries the horizontal delay time.

        Sets the delay of acquisition data so that the resulting waveform is
        centered x ms after the trigger occurs.
        The amount of time the acquisition is delayed depends on sample rate and record length.

        Returns:
            float: The horizontal delay time.
        """
        return float(self.query('HORizontal:DELay:TIMe?'))

    @pre_sample_time.setter
    def pre_sample_time(self, pre_sample_time):
        """
        Sets the horizontal delay time.

        Sets the delay of acquisition data so that the resulting waveform is
        centered x ms after the trigger occurs.
        The amount of time the acquisition is delayed depends on sample rate and record length.

        Args:
            pre_sample_time (float): The horizontal delay time.
        """
        self.write('HORizontal:DELay:TIME {}'.format(str(pre_sample_time)))

    @property
    def pre_sample_ratio(self):
        """
        Queries the pre sample ratio.

        Pre sample ratio is set as a number between 0 and 1, representing the percentage of the total record length:
        0 equals a trigger point at the start of the record, 0% pre samples and 100% post samples
        0.5 equals a trigger point half way the record, 50% pre samples and 50% post samples
        1 equals a trigger point at the end of the record, 100% pre samples and 0% post samples
        By default the pre sample ratio is: 0.5 (trigger point in the middle of the screen).

        Returns:
            float: The pre sample ratio.
        """
        return -self.pre_sample_time / (self.horizontal_scale * 16) + 0.5

    @pre_sample_ratio.setter
    def pre_sample_ratio(self, pre_sample_ratio):
        """
        Sets the pre sample ratio.

        Pre sample ratio is set as a number between 0 and 1, representing the percentage of the total record length:
        0 equals a trigger point at the start of the record, 0% pre samples and 100% post samples
        0.5 equals a trigger point half way the record, 50% pre samples and 50% post samples
        1 equals a trigger point at the end of the record, 100% pre samples and 0% post samples
        By default the pre sample ratio is: 0.5 (trigger point in the middle of the screen).

        Args:
            pre_sample_ratio (float): The pre sample ratio.
        """
        self.pre_sample_time = -(pre_sample_ratio - 0.5 ) * (self.horizontal_scale * 16)


    @property
    def trig_pulse_class(self):
        """
        Queries the type of pulse on which to trigger

        Returns:
            str: The pulse trigger class ('RUNT', 'WIDTH').

                RUNT triggers when a pulse crosses the first preset voltage threshold but does not cross the second
                preset threshold before recrossing the first.

                WIDTH triggers when a pulse is found that has the specified polarity and is either inside or outside
                the specified time limits.
        """
        return self.query('TRIGger:A:PULse:CLAss?').upper()

    @trig_pulse_class.setter
    def trig_pulse_class(self, trigger_pulse_class):
        """
        Queries the type of pulse on which to trigger

        Args:
            trigger_pulse_class (str): The pulse trigger class ('RUNT', 'WIDTH').

                RUNT triggers when a pulse crosses the first preset voltage threshold but does not cross the second
                preset threshold before recrossing the first.

                WIDTH triggers when a pulse is found that has the specified polarity and is either inside or outside
                the specified time limits.
        """
        if trigger_pulse_class == 'RUNT' or trigger_pulse_class == 'RUNt':
            self.write('TRIGGER:A:PULSE:CLASS RUNt')
        elif trigger_pulse_class == 'WIDTH' or trigger_pulse_class == 'WIDth':
            self.write('TRIGGER:A:PULSE:CLASS WIDth')

    @property
    def trigger_time_width(self):
        """
        Queries the width for a runt trigger.

        Returns:
            float:  The width for a runt trigger.
        """
        return float(self.query('TRIGger:A:RUNT:WIDth?'))

    @trigger_time_width.setter
    def trigger_time_width(self, time):
        """
        Sets the width for a runt trigger.

        Args:
            time (float):  The width for a runt trigger.
        """
        self.write('TRIGger:A:RUNT:WIDth {}'.format(str(time)))


    @property
    def fft_ordinate_unit(self):
        """Selected unit for the ordinate of the FFT operation."""
        return self.query('FFT:VType?').upper()

    @fft_ordinate_unit.setter
    def fft_ordinate_unit(self, fft_unit):
        """Select the vertical unit for the FFT operations.

        Args:
            fft_unit: Current FFT vertical unit ('DB or 'LINEAR').
        """
        if fft_unit == 'LINEAR' or fft_unit == 'LINEAr':
            self.write('FFT:VType LINEAr')
        else:
            self.write('FFT:VType DB')

    @property
    def fft_window(self):
        """Selected FFT window."""
        return self.query('FFT:WINdow?').upper()

    @fft_window.setter
    def fft_window(self, window):
        """Select FFT window.

        Args:
            window: Window for the FFT ('HAMMING' 'HANNING' 'RECTANGULAR', 'BLACKMANHARRIS').
        """
        if window.upper() == 'HAMMING':
            self.write('FFT:WINdow HAMming')
        elif window.upper() == 'HANNING':
            self.write('FFT:WINdow HANning')
        elif window.upper() == 'RECTANGULAR':
            self.write('FFT:WINdow RECTangular')
        elif window.upper() == 'BLACKMANHARRIS':
            self.write('FFT:WINdow BLAckmanharris')

    @property
    def fft_horizontal_scale(self):
        """
        Queries the horizontal scale of the FFT waveform in Hz.

        Returns:
            float: The horizontal scale of the FFT waveform.
        """
        return float(self.query("FFT:HORizontal:SCAle?"))

    @fft_horizontal_scale.setter
    def fft_horizontal_scale(self, scale):
        """
        Sets the horizontal scale of the FFT waveform.

        Args:
            scale (float): Scale value to set.
        """
        self.write("FFT:HORizontal:SCAle {}".format(scale))

    @property
    def fft_vertical_scale(self):
        """
        Queries the vertical scale of the FFT waveform in dB.

        Returns:
            float: The vertical scale of the FFT waveform.
        """
        return float(self.query("FFT:VERTical:SCAle?"))

    @fft_vertical_scale.setter
    def fft_vertical_scale(self, scale):
        """
        Sets the vertical scale of the FFT waveform.

        Args:
            scale (float): Scale value to set.
        """
        self.write("FFT:VERTical:SCAle {}".format(scale))

    @property
    def fft_source(self):
        """Get the source of the FFT."""
        return self.query("FFT:SOURce?")

    @fft_source.setter
    def fft_source(self, source):
        """Set the source of the FFT.

        Args:
            source (str): Source of the FFT. ('CH1', 'CH2')
        """
        self.write(":FFT:SOURce1 CHANnel{}".format(source))


class Channel:
    """Channel class for the Oscilloscope."""

    def __init__(self, osc, channel_index):
        self.channel_index = channel_index
        self.osc = osc

    def _write(self, message):
        """Write a message to the visa interface and check for errors."""
        self.osc.write(message)

    def _query(self, message):
        """Send a query to the visa interface and check for errors."""
        value = self.osc.query(message)
        return value

    def get_signal(self):
        if self.enabled:
            """Get the signal of the channel."""
            return self.osc.get_signal("CH{}".format(self.channel_index))
        else:
            return [[]]

    @property
    def _trig_lvl(self):
        """
        Get the trigger level voltage for the active trigger source.
        Each channel can have an independent level.

        Used in Runt trigger as the lower threshold. Used for all other trigger types as the single level/threshold.

        Returns:
            float: The edge trigger voltage level.
        """
        return float(self._query('TRIGger:A:LOWerthreshold:CH{}?'.format(self.channel_index)))

    @_trig_lvl.setter
    def _trig_lvl(self, trig_lvl):
        """
        Set the trigger level voltage for the active trigger source.
        Each channel can have an independent level.

        Used in Runt trigger as the lower threshold. Used for all other trigger types as the single level/threshold.

        Args:
            trig_lvl (float): The edge trigger voltage level.
        """
        self._write('TRIGger:A:LOWerthreshold:CH{} {}'.format(self.channel_index, trig_lvl))

    @property
    def _trig_upper_threshold(self):
        """
        Sets or queries the upper threshold for channel <x>, where x is the channel number.
        Each channel can have an independent level. Used only for runt trigger type.

        Returns:
            float: The upper threshold voltage level.
        """
        return float(self._query('TRIGger:A:UPPerthreshold:CH{}?'.format(self.channel_index)))

    @_trig_upper_threshold.setter
    def _trig_upper_threshold(self, trig_lvl):
        """
        Sets or queries the upper threshold for channel <x>, where x is the channel number.
        Each channel can have an independent level. Used only for runt trigger type.

        Args:
            trig_lvl (float): The upper threshold voltage level.
        """
        self._write('TRIGger:A:UPPerthreshold:CH{} {}'.format(self.channel_index, trig_lvl))


    @property
    def _probe_gain(self):
        """
        Queries the gain factor for the probe attached to the channel.

        The gain of a probe is the output divided by the input transfer ratio.
        For example, a common 10x probe has a gain of 0.1.

        Returns:
            float: The gain factor for the probe.
        """
        return float(self._query('CH{}:PRObe:GAIN?'.format(self.channel_index)))

    @_probe_gain.setter
    def _probe_gain(self, gain):
        """
        Sets the gain factor for the probe attached to the channel.

        The gain of a probe is the output divided by the input transfer ratio.
        For example, a common 10x probe has a gain of 0.1.

        Args:
            gain (float): The gain factor for the probe.
        """
        self._write('CH{}:PRObe:GAIN {}'.format(self.channel_index, gain))

    @property
    def enabled(self):
        """
        Returns whether the channel is on or off but does not indicate whether it is the selected waveform.

        Returns:
            bool: Returns whether the channel is on or off but does not indicate whether it is the selected waveform.
        """
        state = self._query('SELect:CH{}?'.format(self.channel_index))
        if state == '1':
            return True
        else:
            return False

    @enabled.setter
    def enabled(self, state):
        """
        Turns the display of the channel <x> waveform on or off, where <x > is the channel number.
        This command also resets the acquisition.

        Args:
            state (bool): The ON/OFF state of the channel.
        """
        if state:
            self._write('SELect:CH{} ON'.format(self.channel_index))
        else:
            self._write('SELect:CH{} OFF'.format(self.channel_index))

    @property
    def trig_lvl(self):
        """
        Get the trigger level.

        Returns:
            list[float]:
                The lower and upper trigger level if the trigger mode is set to "Transition mode" or
                the trigger level if the trigger mode is set to "Edge triggering" or "Pulse Width triggering"
        """
        if self.osc.trig_type == 'PULSE' and self.osc.trig_pulse_class == 'RUNT':
            trig_lvl = [self._trig_lvl, self._trig_upper_threshold]
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
        if self.osc.trig_type == 'PULSE' and self.osc.trig_pulse_class == 'RUNT':
            self._trig_lvl = min(trig_lvl)
            self._trig_upper_threshold = max(trig_lvl)
        else:
            self._trig_lvl = trig_lvl[0]

    @property
    def attenuation(self):
        """Probe attenuation."""
        return 1/self._probe_gain

    @attenuation.setter
    def attenuation(self, att):
        """Set probe attenuation range for each channel.

        Args:
            att: Attenuation to set.
        """
        self._probe_gain = 1/att

    @property
    def measured_unit(self):
        """Get the measurement unit of the probe."""
        return self._query('CH{}:PRObe:UNIts?'.format(self.channel_index)).upper()

    @property
    def coupling(self):
        """
        Get the input coupling for the specified channel.

        Returns:
            str: The coupling for the selected channel ('AC' or 'DC').
        """
        return self._query('CH{}:COUPling?'.format(self.channel_index)).upper()

    @coupling.setter
    def coupling(self, coupling):
        """
        Set the input coupling for the specified channel.

        The coupling for each analog channel can be set to AC or DC.

        Args:
            coupling (str): The coupling for the selected channel ('AC' or 'DC').
        """
        self._write('CH{}:COUPling  {}'.format(self.channel_index, coupling))


    @property
    def offset(self):
        """
        Queries the vertical offset for channel <x>, where x is the channel number.
        This command offsets the vertical acquisition window (moves the level at the vertical center of the acquisition
        window) for the specified channel. Visualize offset as scrolling the acquisition window towards the top of a
        large signal for increased offset values, and scrolling towards the bottom for decreased offset values.
        The resolution of the vertical window sets the offset increment for this control.
        Offset adjusts only the vertical center of the acquisition window for channel waveforms to help determine what
        data is acquired. The instrument always displays the input signal minus the offset value.
        The channel offset range depends on the vertical scale factor. The valid ranges for the instrument are
        (when the probe and external attenuation factor is X1):
        For V/Div settings from 2 mV/div to 200 mV/div, the offset range is +/- 0.8 V
        For V/Div settings from 202 mV/div to 5 V/div, the offset range is +/- 20 V

        Returns:
            float:
                The current offset value for the selected channel.
        """
        return self._query('CH{}:OFFSet?'.format(self.channel_index))

    @offset.setter
    def offset(self, offset):
        """
        Set the vertical offset for channel <x>, where x is the channel number.
        This command offsets the vertical acquisition window (moves the level at the vertical center of the acquisition
        window) for the specified channel. Visualize offset as scrolling the acquisition window towards the top of a
        large signal for increased offset values, and scrolling towards the bottom for decreased offset values.
        The resolution of the vertical window sets the offset increment for this control.
        Offset adjusts only the vertical center of the acquisition window for channel waveforms to help determine what
        data is acquired. The instrument always displays the input signal minus the offset value.
        The channel offset range depends on the vertical scale factor. The valid ranges for the instrument are
        (when the probe and external attenuation factor is X1):
        For V/Div settings from 2 mV/div to 200 mV/div, the offset range is +/- 0.8 V
        For V/Div settings from 202 mV/div to 5 V/div, the offset range is +/- 20 V

        Args:
            offset (float):
                The current offset value for the selected channel.
        """
        self._write('CH{}:OFFSet {}'.format(self.channel_index, offset))
