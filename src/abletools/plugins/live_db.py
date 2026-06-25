import os
import platform
import sqlite3
import struct


from pathlib import Path
from typing import Any, Optional, Tuple, Union
from uuid import UUID


from abletools.api.plugin import PluginMetadata, Uid
from abletools.plugins.plugin_db import PluginDB, PluginDBError


class LivePluginDB(PluginDB):
    def __init__(self,) -> None:
        self.db_path = _get_ableton_plugin_db_path()
        self.connection: Optional[sqlite3.Connection] = None

    def open_connection(self) -> None:
        try:
            self.connection = sqlite3.connect(str(self.db_path))
        except Exception as e:
            raise PluginDBError(
                f"Could not connect to Live database. Error: {e}")

    def get_metadata(self, device_id: str) -> Optional[PluginMetadata]:
        if not self.connection:
            raise PluginDBError(
                "Cannot query database as connection is not open.")

        query = """
SELECT
    p.name,
    p.vendor,
    p.version,
    p.sdk_version,
    p.subcategories
FROM plugins p
WHERE p.dev_identifier = ?
""".strip()

        cursor = self.connection.cursor()
        cursor.execute(query, (device_id,))
        result = cursor.fetchone()
        if not result:
            return None

        name, vendor, version, sdk_version, subcategories = result

        try:
            return PluginMetadata(
                id=_get_plugin_id(device_id),
                name=name,
                vendor=vendor,
                version=version,
                vst_version=sdk_version,
                subcategories=subcategories
            )
        except Exception as e:
            raise PluginDBError(
                f"Failed to convert Device ID to Plugin ID. Error: {e}")

    def find_matching_vst3(self, **kwargs: Any) -> Optional[PluginMetadata]:
        """
        Try matching by fingerprint first, ensuring that the path ends with ".vst3".
        If that does not work, we try match by converting the VST2 path to a VST3 path, ensuring that the plugin name is a substring of the VST3 plugin name or vice versa and that the vendor and subcategories are the same.
        """

        if not self.connection:
            raise PluginDBError(
                "Cannot query database as connection is not open.")

        strategies = [self._match_by_name,
                      self._match_by_fingerprint, self._match_by_path]

        for strategy in strategies:
            result = strategy(**kwargs)
            if not result:
                continue

            vst3_device_id, name, vendor, version, sdk_version, subcategories = result

            try:
                return PluginMetadata(
                    id=_get_plugin_id(vst3_device_id),
                    name=name,
                    vendor=vendor,
                    version=version,
                    vst_version=sdk_version,
                    subcategories=subcategories
                )
            except Exception as e:
                raise PluginDBError(
                    f"Failed to convert Device ID to Plugin ID. Error: {e}")

        return None

    def _match_by_name(self, **kwargs: Any) -> Optional[Tuple[Any, ...]]:
        """Works for almost all plugins with few exceptions.

        FabFilter decided to name their VST3 plugins differently.
        For instance, the Pro-C 2 VST2 plugin is called "FabFilter Pro-C 2" while the VST3 version is "Pro-C 2".
        """
        if not self.connection:
            return None

        cursor = self.connection.cursor()

        if len(kwargs["vst2_device_id"]) > 0:
            # We can match by the vendor as well
            query = """
SELECT
    p0.dev_identifier,
    p0.name,
    p0.vendor,
    p0.version,
    p0.sdk_version,
    p0.subcategories
FROM plugins p0
INNER JOIN plugins p1
    ON p0.vendor = p1.vendor
AND p0.name = p1.name
AND p0.subcategories = p1.subcategories
WHERE
    p1.dev_identifier = ?
AND p0.dev_identifier <> p1.dev_identifier
AND p0.dev_identifier LIKE '%:vst3:%'
""".strip()
            bindings = (kwargs["vst2_device_id"],)
        else:
            query = """
SELECT
    p.dev_identifier,
    p.name,
    p.vendor,
    p.version,
    p.sdk_version,
    p.subcategories
FROM plugins p
WHERE
    p.dev_identifier LIKE '%:vst3:%'
AND (p.name LIKE '%' || :plugname || '%' OR :plugname LIKE '%' || p.name || '%')
"""
            bindings = {"plugname": kwargs["vst2_plugin_name"]}

        cursor.execute(query, bindings)
        return cursor.fetchone()

    def _match_by_fingerprint(self, **kwargs: Any) -> Optional[Tuple[Any, ...]]:
        """Live stores a fingerprint field in the plugin_modules table which is ostensibly some sort of checksum.
        If the fingerprint for the VST2 and VST3 plugins match, they must be the same plugin.

        This fixes the FabFilter case.
        """

        if not self.connection:
            return None

        query = """
SELECT
    p.dev_identifier,
    p.name,
    p.vendor,
    p.version,
    p.sdk_version,
    p.subcategories
FROM plugins p
INNER JOIN plugin_modules pm
    ON p.module_id = pm.module_id
WHERE pm.path LIKE '%.vst3'
  AND pm.fingerprint = (
      SELECT fingerprint
      FROM plugin_modules
      WHERE module_id = ?
  )
""".strip()

        cursor = self.connection.cursor()
        cursor.execute(query, (kwargs["vst2_device_id"],))
        return cursor.fetchone()

    def _match_by_path(self, **kwargs: Any) -> Optional[Tuple[Any, ...]]:
        """Least reliable as plugins are expected to be located in their default locations.

        Live allows users to specify custom plugin locations so this will likely not work for those plugins.
        """

        if not self.connection:
            return None

        # Assuming that the VST2 is located at the default OS path, we compute where the VST3 version of the plugin should be
        vst3_path = _convert_to_vst3_path(kwargs["vst2_plugin_path"])

        plugin_query = """
SELECT
    p.dev_identifier,
    p.name,
    p.vendor,
    p.version,
    p.sdk_version,
    p.subcategories
FROM plugins p
INNER JOIN plugin_modules pm
    ON p.module_id = pm.module_id
WHERE
    pm.path = ?
""".strip()

        cursor = self.connection.cursor()
        cursor.execute(plugin_query, (str(vst3_path),))
        plugin_result = cursor.fetchone()
        return plugin_result

    def close_connection(self) -> None:
        if self.connection:
            self.connection.close()
        else:
            raise PluginDBError(
                "Cannot close connection as connection is not open.")


def _convert_to_vst3_path(vst2_path: Path) -> Path:
    """
    Converts a default VST2 plugin path to its VST3 equivalent.
    Handles both macOS (.vst) and Windows (.dll) path conventions.
    """
    # MacOS uses .vst extensions and keeps VST/VST3 folders in the same parent directory
    if vst2_path.suffix.lower() == ".vst" or "Plug-Ins/VST" in vst2_path.as_posix():
        # Safely swap the 'VST' directory for 'VST3' without breaking other parts of the path
        new_parts = ["VST3" if part ==
                     "VST" else part for part in vst2_path.parent.parts]
        new_parent = Path(*new_parts)

        return new_parent / f"{vst2_path.stem}.vst3"

    # Windows uses .dll for VST2. While VST2 paths vary wildly, VST3 paths are
    # strictly mandated by Steinberg to be in the Common Files directory
    elif vst2_path.suffix.lower() == ".dll" or vst2_path.drive:
        # Default to C: if the drive letter isn't explicitly in the path
        drive = vst2_path.drive if vst2_path.drive else "C:"
        new_parent = Path(f"{drive}\\Program Files\\Common Files\\VST3")

        return new_parent / f"{vst2_path.stem}.vst3"

    # If the path structure doesn't match standard patterns, just swap the extension
    return vst2_path.with_suffix(".vst3")


def _get_plugin_id(device_id: str) -> Union[int, Uid]:
    """Extracts the plugin id from a plugin's device id.

    For a VST2 device ID in the form "device:vst:<plugin-type>:<id>?n=<name>" it turns into a single integer <id>.

    For a VST3 device ID in the form "device:vst3:<plugin-type>:<UUID>", it turns into a UID tuple of four 32-bit integers."""
    try:
        if "vst3" in device_id:
            return _uuid_to_uid(device_id.split(":")[-1])
        elif "vst" in device_id:
            tail = device_id.split(":")[-1]
            id = tail.split("?")[0]
            return int(id)
    except:
        raise ValueError(
            f"Failed to extract plugin ID from Device ID '{device_id}'.")

    raise ValueError(
        f"Expected Device ID '{device_id}' to point to a 'vst' or 'vst3' plugin.")


def _uuid_to_uid(uuid_str: str) -> Uid:
    """Converts a standard UUID string back into four 32-bit integers for Ableton XML."""
    return struct.unpack(">4i", UUID(uuid_str).bytes)


def _get_ableton_plugin_db_path() -> Optional[Path]:
    current_os = platform.system()
    home = Path.home()

    if current_os == "Darwin":  # macOS
        base_db_dir = home / "Library" / "Application Support" / "Ableton" / "Live Database"
    elif current_os == "Windows":
        # Using os.getenv for APPDATA handles Roaming, but Live Database sits in AppData/Local
        local_appdata = os.getenv("LOCALAPPDATA")
        if not local_appdata:
            base_db_dir = home / "AppData" / "Local" / "Ableton" / "Live Database"
        else:
            base_db_dir = Path(local_appdata) / "Ableton" / "Live Database"
    else:
        raise PluginDBError("Live is not supported on Linux.")

    plugin_db_file = base_db_dir / "Live-plugins-1.db"
    if not plugin_db_file.exists():
        raise PluginDBError("Could not find Live plugin database file.")

    return plugin_db_file
