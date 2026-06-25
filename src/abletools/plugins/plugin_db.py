import abc


from typing import Any, Dict, Optional


from abletools.api.plugin import PluginMetadata


class PluginDBError(Exception):
    pass


class PluginDB(abc.ABC):
    def has_plugin(self, device_id: str) -> bool:
        """Checks if the database contains a plugin with the given device identifier."""
        return self.get_metadata(device_id) is not None

    @abc.abstractmethod
    def get_metadata(self, device_id: str) -> Optional[PluginMetadata]:
        """Returns the plugin metadata for a given device id."""
        pass

    @abc.abstractmethod
    def find_matching_vst3(self, **kwargs: Dict[str, Any]) -> Optional[PluginMetadata]:
        """Matches a VST2 plugin to its corresponding VST3 plugin, if possible."""
        pass
