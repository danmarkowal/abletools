import importlib.util
import inspect
import sys


from pathlib import Path
from typing import Any, Dict, List


from abletools.api.patch import PluginPatch


class PatchError(Exception):
    pass


class PatchRegistry:
    def __init__(self) -> None:
        self._patches: List[PluginPatch] = []

    def load_user_patches(self, dir_path: Path) -> None:
        """Dynamically loads .py files from a user-specified directory.

        :param dir_path: The path to the directory containing the patches to load.
        """

        app_root = str(Path(__file__).parent.absolute())
        if app_root not in sys.path:
            sys.path.append(app_root)

        for file_path in dir_path.glob("*.py"):
            module_name = file_path.stem

            try:
                # Load the file as a module dynamically
                spec = importlib.util.spec_from_file_location(
                    module_name, file_path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    # Look for classes inside the module that inherit from Patch
                    for _, obj in inspect.getmembers(module, inspect.isclass):
                        if issubclass(obj, PluginPatch) and obj is not PluginPatch:
                            # Instantiate and register the patch
                            self._patches.append(obj())
            except Exception as e:
                raise PatchError(
                    f"Failed to load patch file {file_path.name}. Error: {e}")

    def apply_user_patch(self, plugin_data: str, metadata: Dict[str, Any]) -> str:
        """Applies the user patch that matches the given plugin metadata to the plugin data."""
        applicable_patches: List[PluginPatch] = [
            patch for patch in self._patches if patch.should_apply(metadata)]
        if len(applicable_patches) == 0:
            return plugin_data
        if len(applicable_patches) > 1:
            raise PatchError(
                f"Multiple patches found that apply to plugin with metadata {metadata}")
        return applicable_patches[0].apply(plugin_data, metadata)
