import struct
import binascii
import zlib


class PluginDataConverter:
    def __init__(self):
        """Initializes the converter. 
        Ableton's host-level VST3 wrapper strictly uses Little-Endian ('<').
        """
        self.endianness = "<"
        self.version_flag = 1

    def _is_zlib_compressed(self, data: bytes) -> bool:
        """Detects if a byte block is a zlib archive via standard headers."""
        return data.startswith(b'\x78\x01') or data.startswith(b'\x78\x9c') or data.startswith(b'\x78\xda')

    def convert_to_processor_state(self, raw_vst2_buffer_contents: str) -> str:
        """Converts an Ableton VST2 <Buffer> hex string into a VST3 <ProcessorState> 
        hex string using Ableton's actual internal migration layout.
        """
        # Clean up any line breaks or whitespace from the XML block
        clean_hex = "".join(raw_vst2_buffer_contents.split())

        # 1. Decode hex string to raw binary bytes
        try:
            decoded_bytes = binascii.unhexlify(clean_hex)
        except Exception as e:
            raise ValueError(f"Failed to decode hex string. Error: {e}")

        # 2. Check for Ableton's zlib layer and extract the true VST2 payload
        is_compressed = self._is_zlib_compressed(decoded_bytes)
        if is_compressed:
            try:
                vst2_raw_bytes = zlib.decompress(decoded_bytes)
            except Exception as e:
                raise ValueError(
                    f"Failed to decompress zlib payload. Error: {e}")
        else:
            vst2_raw_bytes = decoded_bytes

        # 3. Get the exact size of the VST2 payload
        vst2_length = len(vst2_raw_bytes)

        # 4. Pack Ableton's host migration header (Little-Endian)
        # [4 Bytes: Version (1)] [4 Bytes: VST2 Data Length]
        ableton_header = struct.pack(
            f'{self.endianness}II', self.version_flag, vst2_length)

        # 5. Stitch the migration block together
        vst3_raw_payload = ableton_header + vst2_raw_bytes

        # 6. Match the compression state of the source project file
        if is_compressed:
            # Level 1 compression forces the '78 01' header style seen in Serum
            vst3_final_bytes = zlib.compress(vst3_raw_payload, level=1)
        else:
            vst3_final_bytes = vst3_raw_payload

        # 7. Convert back to the clean uppercase hex format used in .als files
        vst3_processor_state_string = binascii.hexlify(
            vst3_final_bytes).decode("ascii").upper()

        return vst3_processor_state_string
