from typing import Any, Dict

from abletools.api.patch import PluginPatch


class Imager2Patch(PluginPatch):
    @property
    def name(self) -> str:
        return "Ozone Imager 2 Patch"

    def should_apply(self, metadata: Dict[str, Any]) -> bool:
        plugin_name = metadata.get("vst2_plugin_name", "").lower()
        return plugin_name == "Ozone Imager 2".lower()

    def apply(self, hex_data: str, metadata: Dict[str, Any]) -> str:
        # VST2 data has a 4-byte header (8 hex characters)
        # The VST3 format drops this header completely.
        header_hex_length = 8

        # Safely slice off the header if the string is long enough
        if len(hex_data) > header_hex_length:
            return hex_data[header_hex_length:]

        return hex_data
