from typing import Any, Dict

from abletools.api.patch import PluginPatch


class Xpand2Patch(PluginPatch):
    """A patch for converting Xpand!2 plugins from VST2 to VST3."""

    @property
    def name(self) -> str:
        return "Xpand!2"

    def should_apply(self, metadata: Dict[str, Any]) -> bool:
        # Target Xpand!2 specifically. We check a few common string formats
        # just in case the host DAW reports the name slightly differently.
        plugin_name = metadata.get("vst2_plugin_name", "").lower()
        return plugin_name in ["xpand!2", "xpand2", "xpand!2_x64"]

    def apply(self, hex_data: str, metadata: Dict[str, Any]) -> str:
        # VST2 data has a 16-byte header (32 hex characters) representing the
        # chunk size. The VST3 format drops this header completely.
        header_hex_length = 32

        # Safely slice off the header if the string is long enough
        if len(hex_data) > header_hex_length:
            return hex_data[header_hex_length:]

        return hex_data
