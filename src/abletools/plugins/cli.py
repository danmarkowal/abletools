import re
import time


from argparse import Namespace
from enum import Enum
from typing import Any, Dict, Optional
from lxml import etree
from pathlib import Path


from abletools.api.plugin import PluginMetadata
from abletools.plugins.live_db import LivePluginDB
from abletools.plugins.patch_registry import PatchRegistry
from abletools.plugins.plugin_db import PluginDBError
from abletools.plugins.vst_converter import Vst3Converter, VstConversionContext
from abletools.utils.process_utils import is_process_running
from abletools.utils.xml_converter import XMLConversionError, ableton_bool, find_not_null, get_tagged_value
from abletools.utils import project_utils


ABLETON_LIVE_PROJECT_SUFFIX = ".als"


class ConversionMode(Enum):
    ALL = "all"
    NECESSARY = "necessary"

    def __str__(self):
        return self.value


def convert_vst2_to_vst3(args: Namespace):
    if is_process_running("Live"):
        print("Please close Ableton Live before running this command.")
        return

    # 1. Read and decode project file (gzip)
    # 2. Check schema version
    # 3. Find all <VstPluginInfo> tags
    # 4. Convert VST2 plugin info to VST3 plugin info
    # 5. Write VST3 plugin info back to the XML tree
    # 6. Gzip XML file and write it to a new file (do not overwrite old project file)
    root = etree.fromstring(project_utils.read_project_file(
        args.projfile), parser=etree.XMLParser(huge_tree=True))

    try:
        db = LivePluginDB()
        db.open_connection()
    except PluginDBError as e:
        print(f"Error initialising Live plugin database. Error {e}")
        return

    patch_registry = PatchRegistry()
    if args.patchdir:
        patch_registry.load_user_patches(Path(args.patchdir))

    for vst2_info in root.findall(".//VstPluginInfo"):
        try:
            name = get_tagged_value(vst2_info, "PlugName", str)
            if not _should_convert_plugin(name, args.includeplugs, args.ignoreplugs):
                continue

            vst2_device_id = _find_device_id(vst2_info)
            vst2_metadata = db.get_metadata(vst2_device_id)

            if args.mode == ConversionMode.NECESSARY and vst2_metadata is not None:
                continue

            path = get_tagged_value(vst2_info, "Path", Path)

            vst3_metadata = db.find_matching_vst3(
                vst2_device_id=vst2_device_id,
                vst2_plugin_name=name,
                vst2_plugin_path=path)
            if not vst3_metadata:
                # Try matching by name and path for a final time, without access to
                pass

            if vst3_metadata is None:
                raise PluginDBError(
                    f"Could not match VST2 plugin '{name}' to a VST3 plugin. Device ID: {vst2_device_id}")

            metadata: Dict[str, Any] = {}
            _add_vst2_metadata(metadata, vst2_info)
            _add_vst3_metadata(metadata, vst3_metadata)

            ctx = VstConversionContext(patch_registry, metadata)

            vst3_info = Vst3Converter(ctx).convert(vst2_info)
            parent = vst2_info.getparent()
            if parent is not None:
                parent.replace(vst2_info, vst3_info)
        except Exception as e:
            print(f"Failed to convert plugin. Error: {e}")

    db.close_connection()

    proj_path = Path(args.projfile)
    # The new project file name is the same as the old one but with " (Converted YYYY-MM-DD HH-MM-SS)" appended before the file extension
    timestamp = time.strftime("%Y-%m-%d %H-%M-%S")
    new_proj_path = proj_path.with_name(
        f"{proj_path.stem} (Converted {timestamp}){ABLETON_LIVE_PROJECT_SUFFIX}")
    print(f"Writing converted project to: '{new_proj_path}'.")

    # Fix indentation
    etree.indent(root, "\t")

    new_proj_contents = etree.tostring(
        root, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    project_utils.write_project_file(new_proj_path, new_proj_contents)


def _add_vst2_metadata(metadata: Dict[str, Any], vst2_info: etree.Element) -> None:
    # We obtain these from the XML tree because it is not guaranteed that
    # the VST2 plugin is present on the user's computer
    metadata["vst2_plugin_name"] = get_tagged_value(vst2_info, "PlugName", str)
    metadata["vst2_plugin_id"] = get_tagged_value(vst2_info, "UniqueId", int)
    metadata["vst2_plugin_version"] = get_tagged_value(
        vst2_info, "Version", str)
    metadata["vst2_vst_version"] = get_tagged_value(
        vst2_info, "VstVersion", str)

    vst2_preset = find_not_null(vst2_info, "Preset/VstPreset")

    metadata["vst2_program_number"] = get_tagged_value(
        vst2_preset, "ProgramNumber", int)
    metadata["is_on"] = get_tagged_value(vst2_preset, "IsOn", ableton_bool)


def _add_vst3_metadata(metadata: Dict[str, Any], vst3_metadata: PluginMetadata) -> None:
    # These are obtained from the plugin database because the VST3 plugin
    # must be present for it to be replaced
    metadata["vst3_plugin_id"] = vst3_metadata.id
    metadata["vst3_plugin_name"] = vst3_metadata.name
    metadata["vst3_plugin_version"] = vst3_metadata.version
    metadata["vst3_vst_version"] = vst3_metadata.vst_version

    # Assumption: the VST2 and VST3 plugin vendor are idential
    # We have to make this assumption because the XML tree does not contain data
    # about the plugin vendor
    metadata["plugin_vendor"] = vst3_metadata.vendor


def _find_device_id(plugin_info: etree.Element) -> str:
    parent_xpath = "ancestor::PluginDevice[1]//SourceContext//BranchSourceContext"
    results = plugin_info.xpath(parent_xpath)
    if len(results) == 0:
        raise XMLConversionError(
            f"Could not find parent device.")
    if len(results) > 1:
        raise XMLConversionError(
            f"Found multiple parent devices for plugin.")
    return get_tagged_value(results[0], "BranchDeviceId", str)


def _should_convert_plugin(plugin_name: str, include_regex: Optional[re.Pattern[str]], ignore_regex: Optional[re.Pattern[str]]) -> bool:
    # Include if (name in include) AND (name not in ignore)
    if include_regex and not include_regex.search(plugin_name):
        return False
    if ignore_regex and ignore_regex.search(plugin_name):
        return False
    return True
