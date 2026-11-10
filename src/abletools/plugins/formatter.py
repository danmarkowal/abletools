import os


from typing import Dict, List, Tuple


from abletools.plugins.inventory import Inventory, InventoryStatus, PluginFormat, PluginSummary
from abletools.utils.tree import DetailLine, TreeItem
from abletools.utils.tui_utils import Style, format_path, pluralize


# the sections of the inventory: their heading, what they contain and their color
SECTIONS: Dict[InventoryStatus, Tuple[str, str, Style]] = {
    InventoryStatus.NEEDS_VST3: ("No VST3 version installed",
                                 "install these to convert more projects, best first", Style.YELLOW),
    InventoryStatus.MISSING: ("Not installed", "used as VST3 or AU", Style.RED),
    InventoryStatus.CONVERTIBLE: ("Ready to convert", "used as VST2, VST3 version installed", Style.GREEN),
    InventoryStatus.OK: ("No conversion needed", "only used as VST3 or AU", Style.DIM),
}


class InventoryFormatter:
    """Builds a tree of the plugins used across projects, grouped by what has to be done to convert the projects to VST3."""

    def __init__(self, inventory: Inventory, project_path: str):
        self.inventory = inventory
        self.project_path = os.path.abspath(project_path)
        self.project_count = len(
            [project for project in inventory.projects if project.error is None])

    def build(self) -> TreeItem:
        sections: List[TreeItem] = []
        for status, (heading, description, _) in SECTIONS.items():
            plugins = [plugin for plugin in self.inventory.plugins
                       if plugin.status == status]
            if len(plugins) == 0:
                continue
            needs_install = status in (
                InventoryStatus.NEEDS_VST3, InventoryStatus.MISSING)
            sections.append(TreeItem(heading, status=pluralize(len(plugins), "plugin"), note=description,
                                     children=[self._build_plugin_item(
                                         plugin) for plugin in plugins],
                                     expanded=True, flagged=needs_install,
                                     details=lambda status=status: self._get_section_details(status)))

        convertible = len(self.inventory.convertible_projects)
        vst2 = len(self.inventory.vst2_projects)
        note = f"{pluralize(len(self.inventory.plugins), 'plugin')} in {pluralize(self.project_count, 'project')} · " + \
            f"{convertible:,} of {pluralize(vst2, 'project')} with VST2 plugins can be fully converted"
        return TreeItem(format_path(self.project_path), note=note, children=sections, expanded=True, flagged=True,
                        path=self.project_path, details=self._get_summary_details)

    def _build_plugin_item(self, plugin: PluginSummary) -> TreeItem:
        _, _, style = SECTIONS[plugin.status]
        vst2_missing = PluginFormat.VST2 in plugin.projects and plugin.installed.get(
            PluginFormat.VST2) is False
        projects = len(plugin.get_all_projects())

        if plugin.status == InventoryStatus.NEEDS_VST3:
            note = f"blocks {pluralize(len(plugin.blocked_projects), 'project')}"
            if plugin.unblocks > 0:
                note += f" · +{plugin.unblocks:,} fully convertible"
            if vst2_missing:
                # these projects can't even load the plugin right now
                note += " · VST2 not installed either"
                style = Style.RED
        elif plugin.status == InventoryStatus.MISSING:
            missing = [str(format) for format in (PluginFormat.VST3, PluginFormat.AU)
                       if format in plugin.projects and plugin.installed.get(format) is False]
            note = f"{' and '.join(missing)} not installed · in {pluralize(projects, 'project')}"
        elif plugin.status == InventoryStatus.CONVERTIBLE:
            note = f"in {pluralize(projects, 'project')}"
            if vst2_missing:
                note += " · VST2 not installed, converting fixes it"
            if len(plugin.failing_projects) > 0:
                note += f" · can't be converted in {pluralize(len(plugin.failing_projects), 'project')}"
                style = Style.YELLOW
        else:
            note = f"in {pluralize(projects, 'project')}"
            if PluginFormat.AU in plugin.projects and plugin.installed.get(PluginFormat.AU) is None:
                note += " · can't tell if the AU is installed"

        formats = [format for format in PluginFormat if format in plugin.projects]
        children = [TreeItem(f"{format} in {pluralize(len(plugin.projects[format]), 'project')}", flagged=True,
                             children=[self._build_project_item(project, plugin)
                                       for project in sorted(plugin.projects[format], key=str.lower)])
                    for format in formats]
        return TreeItem(plugin.name, status="/".join(str(format) for format in formats), style=style, note=note,
                        children=children, flagged=plugin.status in (
                            InventoryStatus.NEEDS_VST3, InventoryStatus.MISSING),
                        details=lambda: self._get_plugin_details(plugin))

    def _build_project_item(self, project: str, plugin: PluginSummary) -> TreeItem:
        blocked = project in plugin.blocked_projects
        return TreeItem(self._get_project_name(project), status="blocked" if blocked else "",
                        style=Style.YELLOW, path=project, flagged=True,
                        details=lambda: self._get_project_details(project))

    def _get_summary_details(self) -> List[DetailLine]:
        inventory = self.inventory
        blocked = len(inventory.vst2_projects) - \
            len(inventory.convertible_projects)
        lines: List[DetailLine] = [(format_path(self.project_path), Style.BOLD), ("", Style.DEFAULT),
                                   (f"{pluralize(len(inventory.plugins), 'plugin')} are used across "
                                    f"{pluralize(self.project_count, 'project')}.", Style.DEFAULT)]
        if len(inventory.vst2_projects) > 0:
            lines.append((f"{len(inventory.convertible_projects):,} of the {pluralize(len(inventory.vst2_projects), 'project')} "
                          f"with VST2 plugins can be fully converted to VST3. The other {blocked:,} use at least one "
                          "plugin without an installed VST3 version.", Style.DEFAULT))
        lines += [("", Style.DEFAULT),
                  ("Plugins under 'No VST3 version installed' are in the order to install them in: each one lets the most "
                   "extra projects be fully converted, together with the ones above it ('+N fully convertible').", Style.DEFAULT)]
        if not inventory.has_audio_units:
            lines += [("", Style.DEFAULT),
                      ("Live's plugin database has no Audio Units, so it can't be told whether AU plugins are installed. "
                       "Audio Units may be turned off in Live's settings.", Style.DIM)]
        unreadable = [project for project in inventory.projects
                      if project.error is not None]
        if len(unreadable) > 0:
            lines += [("", Style.DEFAULT),
                      (f"Could not be read ({len(unreadable):,})", Style.BOLD)]
            lines += [(f"  {self._get_project_name(project.path)}: {project.error}", Style.RED)
                      for project in unreadable]
        return lines

    def _get_section_details(self, status: InventoryStatus) -> List[DetailLine]:
        heading, _, _ = SECTIONS[status]
        explanations = {
            InventoryStatus.NEEDS_VST3: "These plugins are used as VST2 but have no installed VST3 version, so the projects using "
                                        "them can't be fully converted to VST3. If a plugin has a VST3 version, install it, starting "
                                        "at the top of the list. If it doesn't, converting in 'all' mode keeps the installed VST2 version.",
            InventoryStatus.MISSING: "These plugins are used as VST3 or AU, but that format isn't installed, so the projects "
                                     "using them can't load them.",
            InventoryStatus.CONVERTIBLE: "These plugins are used as VST2 and their VST3 versions are installed, so "
                                         "'abletools convert' can replace them.",
            InventoryStatus.OK: "These plugins are only used as VST3 or AU, so they don't need converting.",
        }
        return [(heading, Style.BOLD), ("", Style.DEFAULT), (explanations[status], Style.DEFAULT)]

    def _get_plugin_details(self, plugin: PluginSummary) -> List[DetailLine]:
        lines: List[DetailLine] = [(plugin.name, Style.BOLD)]
        if plugin.vendor:
            lines.append((f"Vendor: {plugin.vendor}", Style.DEFAULT))

        lines += [("", Style.DEFAULT), ("Formats", Style.BOLD)]
        for format in PluginFormat:
            installed = plugin.installed.get(format)
            state = {True: "installed", False: "not installed",
                     None: "can't tell if installed"}[installed]
            used = plugin.projects.get(format, set())
            if len(used) == 0 and installed is not True:
                continue
            name = plugin.names.get(format)
            alias = f" (called '{name}')" if name and name != plugin.name else ""
            usage = f"used in {pluralize(len(used), 'project')}" if len(
                used) > 0 else "not used"
            lines.append(
                (f"  {format}{alias}: {usage} · {state}", Style.RED if installed is False and len(used) > 0 else Style.DEFAULT))

        lines.append(("", Style.DEFAULT))
        projects = len(plugin.get_all_projects())
        vst2_missing = plugin.installed.get(
            PluginFormat.VST2) is False and PluginFormat.VST2 in plugin.projects
        if plugin.status == InventoryStatus.NEEDS_VST3:
            text = f"If it has a VST3 version, install it to be able to convert the {pluralize(len(plugin.blocked_projects), 'project')} " \
                "that use it as VST2."
            if plugin.unblocks > 0:
                text += f" Together with the plugins above it in the list, that lets {plugin.unblocks:,} more " \
                    "projects be fully converted to VST3."
            else:
                text += " On its own (with the plugins above it) that doesn't fully convert any more projects, because " \
                    "they also use other plugins without a VST3 version."
            if vst2_missing:
                text += " The VST2 version isn't installed either, so these projects can't load it right now."
            lines.append((text, Style.YELLOW))
        elif plugin.status == InventoryStatus.MISSING:
            lines.append(
                (f"Install it so that the {pluralize(projects, 'project')} using it can load it.", Style.RED))
        elif plugin.status == InventoryStatus.CONVERTIBLE:
            text = "The VST3 version is installed, so 'abletools convert' can replace the VST2 version."
            if vst2_missing:
                text += " The VST2 version isn't installed, so the projects using it need converting before they can load it."
            lines.append((text, Style.GREEN))
            if len(plugin.failing_projects) > 0:
                lines += [("", Style.DEFAULT),
                          (f"Its data can't be converted in these projects ({len(plugin.failing_projects):,}), e.g. because "
                           "they were made in an older version of Live:", Style.YELLOW)]
                lines += [(f"  {self._get_project_name(project)}: {error}", Style.DEFAULT)
                          for project, error in sorted(plugin.failing_projects.items(), key=lambda pair: pair[0].lower())]
        else:
            lines.append(("Nothing to do.", Style.DEFAULT))
        return lines

    def _get_project_details(self, project: str) -> List[DetailLine]:
        blockers = sorted((plugin.name for plugin in self.inventory.plugins
                           if project in plugin.blocked_projects), key=str.lower)
        lines: List[DetailLine] = [
            (format_path(project), Style.BOLD), ("", Style.DEFAULT)]
        if project not in self.inventory.vst2_projects:
            lines.append(
                ("This project has no VST2 plugins, so it doesn't need converting.", Style.DEFAULT))
        elif len(blockers) == 0:
            lines.append(
                ("Every VST2 plugin in this project has an installed VST3 version, so it can be fully converted.", Style.GREEN))
        else:
            lines.append(
                (f"Can't be fully converted until these plugins have VST3 versions ({len(blockers):,}):", Style.YELLOW))
            lines += [(f"  {name}", Style.DEFAULT) for name in blockers]
        return lines

    def _get_project_name(self, path: str) -> str:
        if os.path.isfile(self.project_path):
            return os.path.basename(path)
        return os.path.relpath(path, self.project_path)
