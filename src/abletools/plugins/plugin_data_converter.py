import struct
import binascii


class PluginDataConverter:
    def __init__(self, endianness: str = "<"):
        """Initializes the converter. Modern VST3 wrapper persistence typically 
        uses Little-Endian ('<') for the header sequence on x86/ARM architectures.
        """
        self.endianness = endianness
        self.magic_cookie = b'VstW'
        self.wrapper_version = 1

    def _decode_buffer(self, raw_buffer_contents: str) -> bytes:
        """Safely decodes the DAW's XML string payload into bytes."""
        try:
            return binascii.unhexlify(raw_buffer_contents)
        except Exception as e:
            raise ValueError(f"Failed to decode the VST2 buffer. Error: {e}")

    def convert_to_processor_state(self,
                                   raw_vst2_buffer_contents: str,
                                   vst2_unique_id: int,
                                   plugin_version: int = 0,
                                   current_program: int = 0,
                                   is_bypassed: bool = False) -> str:
        """Orchestrates the conversion from a VST2 buffer string into a VST3 
        ProcessorState Base16 string, using the Steinberg VstW wrapper structure.

        https://github.com/steinbergmedia/vst3_public_sdk/blob/a3911a4615dabbfdfd9d181ee26b05c70c289a95/source/vst/utility/vst2persistence.cpp
        """
        # 1. Decode the raw XML buffer string into pure binary bytes
        vst2_chunk_bytes = self._decode_buffer(
            raw_vst2_buffer_contents)
        chunk_size = len(vst2_chunk_bytes)

        # 2. Format the bypass flag (C++ bool serializes as a 32-bit integer here)
        bypass_flag = 1 if is_bypassed else 0

        # 3. Pack the C++ Vst2xState Header
        # Format string: 4s (4-char string), i (int32), i (int32), i (int32), i (int32), i (int32)
        header_format = f'{self.endianness}4siiiii'
        vstw_header = struct.pack(header_format,
                                  self.magic_cookie,   # b'VstW'
                                  self.wrapper_version,  # 1
                                  vst2_unique_id,      # e.g., 1802727781
                                  plugin_version,      # e.g., 1073873926
                                  current_program,     # e.g., 0
                                  bypass_flag)         # e.g., 0 or 1

        # 4. Pack the Vector size prefix
        # The SDK uses a std::vector for the chunk, which serializes its size right before the data.
        vector_prefix = struct.pack(f'{self.endianness}i', chunk_size)

        # 5. Concatenate to form the monolithic VST3 binary payload
        vst3_binary_payload = vstw_header + vector_prefix + vst2_chunk_bytes

        # 6. Encode back to Base16 for the VST3 <ProcessorState> XML node
        vst3_processor_state_string = binascii.hexlify(
            vst3_binary_payload).decode("ascii").upper()

        return vst3_processor_state_string
