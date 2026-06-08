from typing import Optional
import json
import sys


from pathlib import Path
from typing import Dict


from abletools.plugins.component_extractor import ComponentExtractionError, Uid, get_vst3_components
from abletools.utils.path_utils import get_cache_path


# This class contains the GUID for the plugin that Ableton stores
AUDIO_MODULE_CLASS = "Audio Module Class"


class VstIdConversionError(Exception):
    pass


class VstIdConverter:
    """A class to convert and cache VST2 unique IDs to VST3 GUIDs

    cross-platform (Windows & macOS).
    """

    def __init__(self, uid_cache_path: Path):
        """Initializes the converter and loads the JSON cache.

        :param cache_file_path: Absolute or relative path to the JSON cache file.
        """
        self.cache_file_path = uid_cache_path
        self.cache: Dict[str, Uid] = self._load_cache()

    def _load_cache(self) -> Dict[str, Uid]:
        """Loads the JSON cache if it exists, otherwise returns an empty dict."""
        if self.cache_file_path.exists():
            try:
                with open(self.cache_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Convert keys back to string and values to tuples
                    return {k: tuple(v) for k, v in data.items()}
            except (json.JSONDecodeError, IOError):
                print(
                    f"Warning: Failed to read cache at {self.cache_file_path}. Starting fresh.",
                    file=sys.stderr,
                )
        return {}

    def _save_cache(self) -> None:
        """Saves the current cache state back to the JSON file."""
        try:
            # Ensure the directory exists
            self.cache_file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=4)
        except IOError as e:
            print(
                f"Could not save cache to {self.cache_file_path}. Error: {e}",
                file=sys.stderr,
            )

    def convert_to_uid(
        self, vst2_path: Path, vst2_id: str
    ) -> Uid:
        """Retrieves the 4-tuple VST3 GUID components from the cache, or converts it if not cached.

        :param plugin_path: Path to the VST2 plugin.
        :param vst2_id: The 4-character unique ID or hex string of the VST2 plugin.
        :return: A 4-tuple containing the four components of the VST3 GUID.
        """
        # Check cache first
        if vst2_id in self.cache:
            return self.cache[vst2_id]

        try:
            vst3_path = convert_vst2_to_vst3_path(vst2_path)
            if vst3_path is None:
                raise VstIdConversionError(
                    f"Invalid VST2 path provided: {vst2_path}.")
            if not vst3_path.exists():
                raise VstIdConversionError(
                    f"Converted VST3 plugin path '{vst3_path}' does not exist.")
            components = get_vst3_components(vst3_path)
        except ComponentExtractionError as e:
            raise VstIdConversionError(
                f"Failed to extract components for plugin '{vst2_path}'. Error: {e}")

        if AUDIO_MODULE_CLASS not in components:
            raise VstIdConversionError(
                f"Could not find '{AUDIO_MODULE_CLASS}' in components for plugin '{vst3_path}'.")

        return components[AUDIO_MODULE_CLASS].guid_fields


def convert_vst2_to_vst3_path(vst2_path: Path) -> Optional[Path]:
    """
    Converts a VST2 plugin path to its corresponding standard VST3 path.
    Handles MacOS (.vst) and Windows (.dll) conventions.
    """
    if vst2_path.suffix.lower() == '.vst':
        # Change extension to .vst3
        new_path = vst2_path.with_suffix('.vst3')
        parts = list(new_path.parts)

        try:
            # Find the 'VST' directory part and replace it with 'VST3'
            # (Case-insensitive check, exact replacement)
            vst_idx = next(i for i, part in enumerate(
                parts) if part.upper() == 'VST')
            parts[vst_idx] = 'VST3'
            return Path(*parts)

        except StopIteration:
            # If there is no dedicated 'VST' folder in the path,
            # just return the path with the updated extension.
            return new_path

    elif vst2_path.suffix.lower() == '.dll':
        new_path = vst2_path.with_suffix('.vst3')
        parts = list(new_path.parts)

        # Common folders where Windows VST2s were dumped
        vst2_common_folders = ['vstplugins', 'vst2', 'steinberg', 'vst']

        # Find the end of the base VST2 directory to preserve vendor subfolders
        base_idx = -1
        for i, part in enumerate(parts):
            if part.lower() in vst2_common_folders:
                base_idx = i

        if base_idx != -1:
            # Extract everything after the base folder (e.g., Vendor\PluginName.vst3)
            sub_path = parts[base_idx + 1:]

            # Check if original path was 32-bit
            is_32_bit = any('x86' in p.lower() for p in parts[:base_idx + 1])
            drive = parts[0]  # Usually 'C:\'

            # Route to standard Windows VST3 Common Files directory
            program_files = "Program Files (x86)" if is_32_bit else "Program Files"
            base_vst3 = Path(drive) / program_files / "Common Files" / "VST3"

            return base_vst3.joinpath(*sub_path)
        else:
            # If the VST2 was in a completely unrecognized custom folder (e.g., D:\MyAudio\),
            # safely assume the user just wants the extension changed in place.
            return new_path

    return None


def get_default_uid_cache_path() -> Path:
    return get_cache_path() / "uid_cache.json"
