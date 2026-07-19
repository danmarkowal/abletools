import struct
from typing import Any, Dict

from abletools.api.patch import PluginPatch


class KhsPatch(PluginPatch):
    """A patch for converting Kilohearts plugins from VST2 to VST3."""

    @property
    def name(self) -> str:
        return "kHs Patch"

    def should_apply(self, metadata: Dict[str, Any]) -> bool:
        return metadata.get("plugin_vendor", "").lower() == "Kilohearts".lower()

    def apply(self, hex_data: str, metadata: Dict[str, Any]) -> str:
        version = 1
        # Each byte is represented by two hex characters
        payload_size = len(hex_data) // 2

        header = struct.pack('<II', version, payload_size)

        return header.hex().upper() + hex_data
