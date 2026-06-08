import abc
from typing import Any, Dict


class PluginPatch(abc.ABC):
    """Base class that all built-in and user-defined patches must inherit from."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """The human-readable name of the patch."""
        pass

    @abc.abstractmethod
    def should_apply(self, metadata: Dict[str, Any]) -> bool:
        """Determines whether the patch should be applied based on the provided metadata.

        :param metadata: Contextual data (plugin_name, vendor, plugin_version, plugin_path, vst_version, vst2_unique_id, current_program, is_on)
        :return: True if the patch should be applied, False otherwise.
        """
        pass

    @abc.abstractmethod
    def apply(self, hex_data: str, metadata: Dict[str, Any]) -> str:
        """
        Transforms VST2 hex data into VST3 hex data.

        :param hex_data: The original VST2 plugin data as a hex string.
        :param metadata: Contextual data (plugin_name, vendor, plugin_version, plugin_path, vst_version, vst2_unique_id, current_program, is_on)
        :return: The modified VST3 hex string.
        """
        pass
