import copy
import logging
import os
import re
import time


from collections import Counter
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple
from lxml import etree
from pathlib import Path


from abletools.api.plugin import PluginMetadata
from abletools.plugins.live_db import LivePluginDB
from abletools.plugins.patch_registry import PatchRegistry
from abletools.plugins.vst_converter import Vst3Converter, VstConversionContext
from abletools.utils.xml_converter import XMLConversionError, ableton_bool, find_not_null, get_tagged_value
from abletools.utils import project_utils

# pre-compile regex
# converted projects are named '<name> (Converted YYYY-MM-DD HH-MM-SS).als'
CONVERTED_PATTERN = re.compile(
    r'^(.*) \(Converted \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\)$')


class ConversionMode(Enum):
    ALL = "all"
    NECESSARY = "necessary"

    def __str__(self):
        return self.value


class PluginStatus(Enum):
    CONVERT = auto()  # the plugin will be converted
    INSTALLED = auto()  # the VST2 plugin is installed, so it is only converted in 'all' mode
    KEPT = auto()  # the VST2 plugin is installed but can't be converted, so 'all' mode keeps it
    NO_VST3 = auto()  # no matching VST3 plugin is installed
    IGNORED = auto()  # the plugin is excluded by --include-plugins or --ignore-plugins
    ERROR = auto()  # the plugin can't be converted, e.g. because its data is missing tags in older Live sets


@dataclass
class ConversionOptions:
    mode: ConversionMode = field(default=ConversionMode.NECESSARY)
    # only plugins whose names match this are converted
    include_plugins: Optional[re.Pattern[str]] = field(default=None)
    # plugins whose names match this are not converted
    ignore_plugins: Optional[re.Pattern[str]] = field(default=None)


@dataclass
class PluginPlan:
    """What converting a VST2 plugin would do. Everything except the mode is worked out in advance, so the mode can be changed without planning again."""
    name: str = field()
    # whether the VST2 plugin is in the Live database, i.e. installed
    installed: bool = field(default=False)
    # the vendor of the plugin, if it is installed as VST2 or VST3
    vendor: Optional[str] = field(default=None)
    # the name of the VST3 plugin that would replace it, if one was found
    vst3_name: Optional[str] = field(default=None)
    # whether --include-plugins or --ignore-plugins exclude the plugin
    ignored: bool = field(default=False)
    # why the plugin can't be converted, e.g. if its data couldn't be read or converted
    error: Optional[str] = field(default=None)
    # the contextual data that patches are given (see PluginPatch)
    metadata: Dict[str, Any] = field(default_factory=lambda: {})

    def get_status(self, mode: ConversionMode) -> PluginStatus:
        # the checks happen in the same order as during the conversion
        if self.ignored:
            return PluginStatus.IGNORED
        if self.installed and mode == ConversionMode.NECESSARY:
            return PluginStatus.INSTALLED
        # an installed VST2 plugin still works, so there is no need to fail if it can't be converted
        if self.installed and (self.error is not None or self.vst3_name is None):
            return PluginStatus.KEPT
        if self.error is not None:
            return PluginStatus.ERROR
        if self.vst3_name is None:
            return PluginStatus.NO_VST3
        return PluginStatus.CONVERT


@dataclass
class ProjectPlan:
    # the absolute path of the project file
    path: str = field()
    # the VST2 plugins in the project, once for each instance of a plugin
    plugins: List[PluginPlan] = field(default_factory=lambda: [])
    # the number of VST3 plugins in the project
    vst3_count: int = field(default=0)
    # why the project file could not be read, if it could not be read
    error: Optional[str] = field(default=None)

    def count(self, mode: ConversionMode) -> Counter[PluginStatus]:
        return Counter(plugin.get_status(mode) for plugin in self.plugins)


@dataclass
class ConversionResult:
    # the path of the converted project file, or None if nothing was converted so no file was written
    path: Optional[Path] = field()
    # what happened to each VST2 plugin
    plans: List[PluginPlan] = field(default_factory=lambda: [])
    # the names of the plugins that were converted
    converted: List[str] = field(default_factory=lambda: [])
    # the names of the installed VST2 plugins that were kept because they couldn't be converted
    kept: List[str] = field(default_factory=lambda: [])
    # the plugins that should have been converted but couldn't be, with the reason
    # (plugins that were known not to be convertible beforehand, e.g. because there is no VST3 version, are not included)
    failed: List[str] = field(default_factory=lambda: [])


def plan_project_file(path: str, options: ConversionOptions) -> ProjectPlan:
    """Works out what converting a project would do, without changing anything. Used by worker processes so it must not raise."""
    path = os.path.abspath(path)
    try:
        root = read_project_xml(Path(path))
        # each worker process needs its own connection
        db = LivePluginDB()
        db.open_connection()
        try:
            plugins = [plan for _, plan in plan_plugins(root, db, options)]
        finally:
            db.close_connection()
        return ProjectPlan(path, plugins, len(root.findall(".//Vst3PluginInfo")))
    except Exception as e:
        return ProjectPlan(path, error=str(e))


def get_original_name(project_file: str) -> Optional[str]:
    """Returns the name of the project that a converted project was converted from, or None if the project wasn't converted."""
    match = CONVERTED_PATTERN.match(Path(project_file).stem)
    return match.group(1) if match else None


def convert_project(project_file: Path, db: LivePluginDB, patch_registry: PatchRegistry, options: ConversionOptions) -> ConversionResult:
    """Converts the VST2 plugins in a project to VST3 plugins and saves the result next to the project file.

    The original project file is never changed, and no file is written if no plugins were converted.
    """
    logging.info(
        f"Starting VST2 to VST3 conversion for project file: '{project_file}'.")

    # 1. Read and decode project file (gzip)
    # 2. Check schema version
    # 3. Find all <VstPluginInfo> tags
    # 4. Convert VST2 plugin info to VST3 plugin info
    # 5. Write VST3 plugin info back to the XML tree
    # 6. Gzip XML file and write it to a new file (do not overwrite old project file)
    root = read_project_xml(project_file)

    result = ConversionResult(None)
    for vst2_info, plan in plan_plugins(root, db, options):
        result.plans.append(plan)
        status = plan.get_status(options.mode)
        if status in (PluginStatus.IGNORED, PluginStatus.INSTALLED):
            continue
        if status == PluginStatus.KEPT:
            reason = "no matching VST3 plugin is installed" if plan.error is None else \
                f"it can't be converted ({plan.error})"
            logging.info(
                f"Kept the installed VST2 plugin '{plan.name}' because {reason}.")
            result.kept.append(plan.name)
            continue
        if status == PluginStatus.ERROR:
            logging.error(
                f"Failed to convert plugin '{plan.name}'. Error: {plan.error}")
            continue
        if status == PluginStatus.NO_VST3:
            logging.error(
                f"Failed to convert plugin '{plan.name}'. Error: Could not match VST2 plugin '{plan.name}' to a VST3 plugin.")
            continue

        try:
            logging.info(
                f"Matched VST2 plugin '{plan.name}' to VST3 plugin '{plan.vst3_name}'.")

            metadata = plan.metadata
            ctx = VstConversionContext(patch_registry, metadata)

            vst3_info = Vst3Converter(ctx).convert(vst2_info)
            parent = vst2_info.getparent()
            if parent is not None:
                parent.replace(vst2_info, vst3_info)

            logging.info(
                f"Converted VST2 plugin '{metadata['vst2_plugin_name']}' ({metadata['vst2_plugin_id']}) to VST3 plugin '{metadata['vst3_plugin_name']}' ({metadata['vst3_plugin_id']}).")
            result.converted.append(plan.name)
        except Exception as e:
            # the VST2 plugin is only replaced once its conversion has worked, so it is still there
            if plan.installed:
                logging.warning(
                    f"Kept the installed VST2 plugin '{plan.name}' because it could not be converted. Error: {e}")
                result.kept.append(plan.name)
                continue
            logging.error(
                f"Failed to convert plugin '{plan.name}'. Error: {e}")
            result.failed.append(f"{plan.name}: {e}")

    if len(result.converted) == 0:
        logging.info(
            "No plugins were converted, so no new project file was written.")
        return result

    # The new project file name is the same as the old one but with " (Converted YYYY-MM-DD HH-MM-SS)" appended before the file extension
    timestamp = time.strftime("%Y-%m-%d %H-%M-%S")
    result.path = project_file.with_name(
        f"{project_file.stem} (Converted {timestamp}){project_utils.ABLETON_LIVE_PROJECT_SUFFIX}")

    # Fix indentation
    etree.indent(root, "\t")

    logging.info(f"Writing converted project to: '{result.path}'.")

    new_proj_contents = etree.tostring(
        root, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    project_utils.write_project_file(result.path, new_proj_contents)
    return result


def read_project_xml(project_file: Path) -> etree.Element:
    return etree.fromstring(project_utils.read_project_file(
        project_file), parser=etree.XMLParser(huge_tree=True))


def plan_plugins(root: etree.Element, db: LivePluginDB, options: ConversionOptions) -> List[Tuple[etree.Element, PluginPlan]]:
    """Works out what converting each VST2 plugin in a project would do."""
    return [(vst2_info, _plan_plugin(vst2_info, db, options)) for vst2_info in root.findall(".//VstPluginInfo")]


def _plan_plugin(vst2_info: etree.Element, db: LivePluginDB, options: ConversionOptions) -> PluginPlan:
    plan = PluginPlan("Unknown plugin")
    try:
        plan.name = get_tagged_value(vst2_info, "PlugName", str)
        if not _should_convert_plugin(plan.name, options.include_plugins, options.ignore_plugins):
            plan.ignored = True
            return plan

        try:
            vst2_device_id = _find_device_id(vst2_info)
        except XMLConversionError:
            # Some Live sets don't say which device a plugin is, so it can only be matched by its name
            vst2_device_id = ""

        if len(vst2_device_id) > 0:
            # If VST2 meta data is not none, then the plugin was found in the Live database
            vst2_metadata = db.get_metadata(vst2_device_id)
            plan.installed = vst2_metadata is not None
            if vst2_metadata is not None:
                plan.vendor = vst2_metadata.vendor
        else:
            plan.installed = db.has_plugin_named("vst", plan.name)

        # Live 10 and earlier don't store the path of the plugin, which is only needed to match plugins by their path
        path_element = vst2_info.find("Path")
        path = Path(path_element.get("Value", "")
                    ) if path_element is not None else None
        vst3_metadata = db.find_matching_vst3(
            vst2_device_id=vst2_device_id,
            vst2_plugin_name=plan.name,
            vst2_plugin_path=path)

        _add_vst2_metadata(plan.metadata, vst2_info)
        if vst3_metadata is not None:
            plan.vst3_name = vst3_metadata.name
            plan.vendor = plan.vendor or vst3_metadata.vendor
            _add_vst3_metadata(plan.metadata, vst3_metadata)
            # Try converting a copy (the converter moves tags out of the original), so that plugins whose data can't be
            # converted, e.g. in older Live sets, are known in advance. Patches are checked separately.
            Vst3Converter(VstConversionContext(PatchRegistry(), plan.metadata)).convert(
                copy.deepcopy(vst2_info))
    except Exception as e:
        plan.error = str(e)
    return plan


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
