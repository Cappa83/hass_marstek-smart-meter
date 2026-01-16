"""API for Marstek CT Meter."""
import socket
import logging

_LOGGER = logging.getLogger(__name__)

SOH = 0x01
STX = 0x02
ETX = 0x03

class MarstekCtApi:
    """API to communicate with the Marstek CT meter."""

    def __init__(self, host, device_type, battery_mac, ct_mac, ct_type):
        self._host = host
        self._port = 12345
        self._device_type = device_type
        self._battery_mac = battery_mac
        self._ct_mac = ct_mac
        self._ct_type = ct_type
        self._timeout = 5.0
        self._payload = self._build_payload()

    def _build_payload(self) -> bytes:
        """Builds the UDP payload for the query."""
        SEPARATOR = "|"
        message_fields = [self._device_type, self._battery_mac, self._ct_type, self._ct_mac, "0", "0"]
        message_bytes = (SEPARATOR + SEPARATOR.join(message_fields)).encode("ascii")

        # Frame: SOH STX <len_ascii> <message_bytes> ETX <xor_hex_2>
        # len = total bytes INCLUDING SOH..ETX and the xor (2 ascii) ??? -> vendor specific.
        # We keep the original length logic but make it consistent.
        base_size_without_len = 1 + 1 + len(message_bytes) + 1 + 2  # SOH+STX + msg + ETX + xor(2)
        # Find length-string length by iterative stabilization
        length_str = str(base_size_without_len + len(str(base_size_without_len)))
        while True:
            total_length = base_size_without_len + len(length_str)
            new_length_str = str(total_length)
            if new_length_str == length_str:
                break
            length_str = new_length_str

        payload = bytearray([SOH, STX])
        payload.extend(length_str.encode("ascii"))
        payload.extend(message_bytes)
        payload.append(ETX)

        xor_val = 0
        for b in payload:
            xor_val ^= b
        payload.extend(f"{xor_val:02x}".encode("ascii"))
        return bytes(payload)

    def _extract_message_ascii(self, data: bytes) -> str:
        """Extract the ascii message between the first '|' and ETX."""
        try:
            etx_pos = data.index(bytes([ETX]))
        except ValueError:
            raise ValueError("ETX not found in response")

        # Everything before ETX includes SOH/STX/len_ascii and message. We only need message part.
        frame = data[:etx_pos]
        # Find first separator (|). Message begins with |...|...
        try:
            pipe_pos = frame.index(b"|")
        except ValueError:
            raise ValueError("No '|' separator found in response")

        msg_bytes = frame[pipe_pos:]  # starts with '|'
        return msg_bytes.decode("ascii")

    def _decode_response(self, data: bytes) -> dict:
        """Parses the UDP response."""
        try:
            message = self._extract_message_ascii(data)
        except (UnicodeDecodeError, ValueError) as e:
            return {"error": f"Invalid response format: {e}"}

        fields = message.split("|")[1:]  # drop leading empty before first '|'

        labels = [
            "meter_dev_type", "meter_mac_code", "hhm_dev_type", "hhm_mac_code",
            "A_phase_power", "B_phase_power", "C_phase_power", "total_power",
            "A_chrg_nb", "B_chrg_nb", "C_chrg_nb", "ABC_chrg_nb", "wifi_rssi",
            "info_idx", "x_chrg_power", "A_chrg_power", "B_chrg_power", "C_chrg_power",
            "ABC_chrg_power", "x_dchrg_power", "A_dchrg_power", "B_dchrg_power",
            "C_dchrg_power", "ABC_dchrg_power",
        ]

        parsed: dict[str, object] = {}
        for i, label in enumerate(labels):
            val = fields[i] if i < len(fields) else None
            if val is None or val == "":
                parsed[label] = None
                continue
            # Some fields may be non-numeric ids -> keep as string
            try:
                parsed[label] = int(val)
            except ValueError:
                parsed[label] = val

        return parsed

    def fetch_data(self) -> dict:
        """Fetch data from the meter. This is a blocking call."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self._timeout)
        try:
            sock.sendto(self._payload, (self._host, self._port))
            response, _ = sock.recvfrom(2048)
            return self._decode_response(response)
        except socket.timeout:
            return {"error": "Timeout - No response from meter"}
        except Exception as e:
            _LOGGER.warning("An unexpected error occurred: %s", str(e))
            return {"error": f"An unexpected error occurred: {str(e)}"}
        finally:
            sock.close()

    def test_connection(self) -> dict:
        """A simple blocking call to test connectivity."""
        return self.fetch_data()


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""
