import os


from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


from lxml import etree


from abletools.plugins.conversion import ConversionOptions, plan_plugins, read_project_xml
from abletools.plugins.live_db import LivePluginDB
from abletools.utils.xml_converter import get_tagged_value


class PluginFormat(Enum):
    VST2 = "VST2"
    VST3 = "VST3"
    AU = "AU"

    def __str__(self):
        return self.value


class InventoryStatus(Enum):
    # used as VST2 but no VST3 version is installed, so projects can't be fully converted
    NEEDS_VST3 = auto()
    MISSING = auto()  # used as VST3 or AU but not installed
    CONVERTIBLE = auto()  # used as VST2 and the VST3 version is installed
    OK = auto()  # only used as VST3 or AU, and installed (as far as we can tell)


@dataclass
class PluginUse:
    """One instance of a plugin in a project."""
    name: str = field()
    format: PluginFormat = field()
    vendor: Optional[str] = field(default=None)
    # whether this format of the plugin is installed, or None if that can't be told
    installed: Optional[bool] = field(default=None)
    # for VST2 plugins: the installed VST3 plugin that the converter would replace it with
    vst3_name: Optional[str] = field(default=None)
    # for VST2 plugins: why converting it would fail even though there is a VST3 version, e.g. in old Live sets
    conversion_error: Optional[str] = field(default=None)


@dataclass
class ProjectPlugins:
    # the absolute path of the project file
    path: str = field()
    uses: List[PluginUse] = field(default_factory=lambda: [])
    # why the project file could not be read, if it could not be read
    error: Optional[str] = field(default=None)


@dataclass
class PluginSummary:
    """A plugin used across projects, in any of its formats."""
    # the VST3 name if there is a VST3 version, since the VST2 name sometimes has the vendor in front of it
    name: str = field()
    vendor: Optional[str] = field(default=None)
    # the names this plugin has in each format, if they differ
    names: Dict[PluginFormat, str] = field(default_factory=lambda: {})
    # the project files that use each format of the plugin
    projects: Dict[PluginFormat, Set[str]] = field(
        default_factory=lambda: {})
    # whether each format is installed, or None if that can't be told
    installed: Dict[PluginFormat, Optional[bool]] = field(
        default_factory=lambda: {})
    status: InventoryStatus = field(default=InventoryStatus.OK)
    # the projects that can't be fully converted to VST3 because this plugin has no VST3 version
    blocked_projects: Set[str] = field(default_factory=lambda: set())
    # the projects where converting this plugin fails even though it has a VST3 version, with the reason
    failing_projects: Dict[str, str] = field(default_factory=lambda: {})
    # how many more projects could be fully converted if this plugin's VST3 version (and those of the plugins
    # before it in the install order) were installed
    unblocks: int = field(default=0)

    def get_all_projects(self) -> Set[str]:
        return {project for projects in self.projects.values() for project in projects}


@dataclass
class Inventory:
    plugins: List[PluginSummary] = field()
    # the projects that were read, including the ones that could not be read
    projects: List[ProjectPlugins] = field()
    # the projects with VST2 plugins, and those of them that can be fully converted to VST3 as things are
    vst2_projects: Set[str] = field()
    convertible_projects: Set[str] = field()
    # whether Live lists any Audio Units; if not, it can't be told whether AU plugins are installed
    has_audio_units: bool = field()


def read_project_plugins(path: str) -> ProjectPlugins:
    """Finds the plugins used in a project and whether they are installed. Used by worker processes so it must not raise."""
    path = os.path.abspath(path)
    try:
        root = read_project_xml(Path(path))
        db = LivePluginDB()
        db.open_connection()
        try:
            return ProjectPlugins(path, _find_plugin_uses(root, db))
        finally:
            db.close_connection()
    except Exception as e:
        return ProjectPlugins(path, error=str(e))


def has_audio_units() -> bool:
    db = LivePluginDB()
    db.open_connection()
    try:
        return db.has_format("au")
    finally:
        db.close_connection()


def take_inventory(projects: List[ProjectPlugins], audio_units: bool) -> Inventory:
    """Combines the plugins of each project into one summary per plugin."""
    summaries: Dict[str, PluginSummary] = {}
    # the plugins without a VST3 version in each project
    blockers: Dict[str, Set[str]] = {}
    # the projects with plugins that can't be converted whatever is installed
    failing: Set[str] = set()

    for project in projects:
        for use in project.uses:
            # a VST2 plugin and its VST3 version are the same plugin
            name = use.vst3_name or use.name
            key = name.lower()
            summary = summaries.setdefault(key, PluginSummary(name))
            summary.vendor = summary.vendor or use.vendor
            summary.names.setdefault(use.format, use.name)
            summary.projects.setdefault(use.format, set()).add(project.path)
            _update_installed(summary, use)

            if use.format == PluginFormat.VST2:
                blockers.setdefault(project.path, set())
                if use.vst3_name is None:
                    blockers[project.path].add(key)
                    summary.blocked_projects.add(project.path)
                elif use.conversion_error is not None:
                    failing.add(project.path)
                    summary.failing_projects[project.path] = use.conversion_error

    for summary in summaries.values():
        summary.status = _get_status(summary)

    vst2_projects = set(blockers)
    # installing plugins can't help the projects whose plugins fail to convert anyway
    for project in failing:
        del blockers[project]
    convertible = {project for project,
                   keys in blockers.items() if len(keys) == 0}
    plugins = sorted(summaries.values(), key=lambda summary: (
        -len(summary.get_all_projects()), summary.name.lower()))
    _order_by_install_benefit(plugins, summaries, blockers)
    return Inventory(plugins, projects, vst2_projects, convertible, audio_units)


def _find_plugin_uses(root: etree.Element, db: LivePluginDB) -> List[PluginUse]:
    uses: List[PluginUse] = []
    # the converter already works out whether VST2 plugins are installed and what they would be converted to
    for _, plan in plan_plugins(root, db, ConversionOptions()):
        uses.append(PluginUse(plan.name, PluginFormat.VST2, plan.vendor, plan.installed, plan.vst3_name,
                              plan.error if plan.vst3_name is not None else None))

    for info in root.iter("Vst3PluginInfo"):
        use = PluginUse(get_tagged_value(
            info, "Name", str), PluginFormat.VST3)
        uid = _get_uid(info)
        if uid is not None:
            found = db.find_vst3(uid)
            use.installed = found is not None
            if found is not None:
                use.name, use.vendor = found
        uses.append(use)

    audio_units = db.has_format("au")
    for info in root.iter("AuPluginInfo"):
        name = get_tagged_value(info, "Name", str)
        manufacturer = info.find("Manufacturer")
        use = PluginUse(name, PluginFormat.AU,
                        manufacturer.get("Value") if manufacturer is not None else None)
        use.installed = db.has_plugin_named(
            "au", name) if audio_units else None
        uses.append(use)
    return uses


def _get_uid(info: etree.Element) -> Optional[Tuple[int, int, int, int]]:
    """Reads the UID of a VST3 plugin, e.g. <Uid><Fields.0 Value="1448301638" />...</Uid>."""
    uid = info.find("Uid")
    if uid is None:
        return None
    try:
        fields = [get_tagged_value(uid, f"Fields.{i}", int) for i in range(4)]
    except Exception:
        return None
    return (fields[0], fields[1], fields[2], fields[3])


def _update_installed(summary: PluginSummary, use: PluginUse):
    if use.installed is not None:
        # if any project finds the plugin, it is installed
        summary.installed[use.format] = summary.installed.get(
            use.format) or use.installed
    if use.format == PluginFormat.VST2:
        # VST2 plugins are matched to installed VST3 plugins, so this also tells whether the VST3 version is installed
        has_vst3 = use.vst3_name is not None
        summary.installed[PluginFormat.VST3] = summary.installed.get(
            PluginFormat.VST3) or has_vst3


def _get_status(summary: PluginSummary) -> InventoryStatus:
    if len(summary.blocked_projects) > 0:
        return InventoryStatus.NEEDS_VST3
    for format in (PluginFormat.VST3, PluginFormat.AU):
        if format in summary.projects and summary.installed.get(format) is False:
            return InventoryStatus.MISSING
    if PluginFormat.VST2 in summary.projects:
        return InventoryStatus.CONVERTIBLE
    return InventoryStatus.OK


def _order_by_install_benefit(plugins: List[PluginSummary], summaries: Dict[str, PluginSummary], blockers: Dict[str, Set[str]]):
    """Orders the plugins that need a VST3 version by how many projects installing it would let be fully converted.

    Each step picks the plugin that, together with the ones picked before it, completes the most projects.
    The other plugins keep their order.
    """
    remaining = [key for key, summary in summaries.items()
                 if summary.status == InventoryStatus.NEEDS_VST3]
    installed: Set[str] = set()
    converted = {project for project, keys in blockers.items()
                 if len(keys) == 0}
    order: List[str] = []

    while len(remaining) > 0:
        # ties go to the plugin that blocks the most projects
        best = max(remaining, key=lambda key: (len(_get_completed(blockers, converted, installed | {key})),
                                               len(summaries[key].blocked_projects)))
        newly_done = _get_completed(blockers, converted, installed | {best})
        summaries[best].unblocks = len(newly_done)
        converted |= newly_done
        installed.add(best)
        remaining.remove(best)
        order.append(best)

    position = {key: i for i, key in enumerate(order)}
    plugins.sort(key=lambda summary: position.get(
        summary.name.lower(), len(position)))


def _get_completed(blockers: Dict[str, Set[str]], converted: Set[str], installed: Set[str]) -> Set[str]:
    """Returns the projects that aren't converted yet but could be fully converted if the given plugins had VST3 versions."""
    return {project for project, keys in blockers.items()
            if project not in converted and keys <= installed}
