import abc
from typing import Any, Dict


class PluginPatch(abc.ABC):
    """Base class that all built-in and user-defined patches must inherit from.

    Contextual data contains the following keys:
        - vst2_plugin_name: str
        - vst2_plugin_id: int
        - vst2_plugin_version: str
        - vst2_vst_version: str
        - vst2_program_number: int

        - vst3_plugin_name: str
        - vst3_plugin_id: Tuple[int, int, int, int]
        - vst3_plugin_version: str
        - vst3_vst_version: str

        - plugin_vendor: str
        - is_on: bool
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """The human-readable name of the patch."""
        pass

    @abc.abstractmethod
    def should_apply(self, metadata: Dict[str, Any]) -> bool:
        """Determines whether the patch should be applied based on the provided metadata.

        :param metadata: Contextual data
        """
        pass

    @abc.abstractmethod
    def apply(self, hex_data: str, metadata: Dict[str, Any]) -> str:
        """
        Transforms VST2 hex data into VST3 hex data.

        :param hex_data: The original VST2 plugin data as a hex string.
        :param metadata: Contextual data
        :return: The modified VST3 hex string.
        """
        pass
