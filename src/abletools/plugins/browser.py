import logging
import os


from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple


from abletools.api.patch import PluginPatch
from abletools.plugins.conversion import ConversionMode, ConversionOptions, PluginPlan, PluginStatus, ProjectPlan, convert_project, get_original_name, plan_project_file
from abletools.plugins.live_db import LivePluginDB
from abletools.plugins.patch_registry import PatchRegistry
from abletools.utils.tree import DetailLine, TreeItem
from abletools.utils.tree_browser import BrowserAction
from abletools.utils.tui_utils import Style, format_path, pluralize


# how many plugin names a note lists before it shortens the rest to '+3 more'
MAX_LISTED_PLUGINS = 3

# the status shown next to a plugin
STATUS_LABELS: Dict[PluginStatus, Tuple[str, Style]] = {
    PluginStatus.CONVERT: ("converts", Style.CYAN),
    PluginStatus.INSTALLED: ("installed", Style.DIM),
    PluginStatus.KEPT: ("kept", Style.DIM),
    PluginStatus.NO_VST3: ("no VST3", Style.RED),
    PluginStatus.IGNORED: ("ignored", Style.DIM),
    PluginStatus.ERROR: ("error", Style.RED),
}
# how a number of plugins with a status is described, e.g. '3 installed'
STATUS_COUNTS: Dict[PluginStatus, str] = {
    PluginStatus.CONVERT: "to convert",
    PluginStatus.INSTALLED: "installed",
    PluginStatus.KEPT: "kept as VST2",
    PluginStatus.NO_VST3: "without VST3",
    PluginStatus.IGNORED: "ignored",
    PluginStatus.ERROR: "with errors",
}
# the headings in the details of a project
STATUS_HEADINGS: Dict[PluginStatus, str] = {
    PluginStatus.CONVERT: "Will be converted",
    PluginStatus.INSTALLED: "Installed, so they stay VST2 in 'necessary' mode (press m to convert them too)",
    PluginStatus.KEPT: "Installed but without a VST3 version, so the VST2 version is kept",
    PluginStatus.NO_VST3: "Not installed, and no matching VST3 plugin is installed either",
    PluginStatus.ERROR: "Can't be converted",
    PluginStatus.IGNORED: "Excluded by --include-plugins or --ignore-plugins",
}


class ConversionBrowser:
    """Builds a tree of projects and patches for the tree browser, showing what converting each project would do.

    Each project contains its VST2 plugins, followed by the versions of it that were converted before.
    """

    def __init__(self, project_path: str, plans: List[ProjectPlan], patches: List[Tuple[PluginPatch, str, bool]],
                 db: LivePluginDB, options: ConversionOptions):
        """
        :param project_path: The project file or folder that was scanned.
        :param plans: What converting each project file would do.
        :param patches: Each patch, where it comes from (e.g. 'built-in') and whether it starts off ticked.
        """
        self.project_path = os.path.abspath(project_path)
        self.db = db
        self.options = options
        self._plans: Dict[str, ProjectPlan] = {
            plan.path: plan for plan in plans}
        self._project_items: Dict[str, TreeItem] = {}
        # the converted versions of each project file, and the reverse
        self._versions: Dict[str, List[str]] = {}
        self._originals: Dict[str, str] = {}
        # the items of the plugins in each project file, by plugin name
        self._plugin_items: Dict[str, List[Tuple[str, TreeItem]]] = {}
        # the project file of each plugin item, by item id
        self._plugin_projects: Dict[int, str] = {}
        # the log messages of the last conversion of a project, by the path of the project and of its converted version
        self._logs: Dict[str, List[logging.LogRecord]] = {}

        self._patch_items: List[Tuple[PluginPatch, TreeItem]] = [
            (patch, TreeItem(patch.name, checked=enabled, flagged=True,
                             details=lambda patch=patch, source=source: self._get_patch_details(patch, source)))
            for patch, source, enabled in patches]
        self._patch_sources = {id(patch): source for patch,
                               source, _ in patches}

    def build(self) -> TreeItem:
        # converted versions go inside the project they were converted from, if it is still there
        top_level: List[str] = []
        for path in sorted(self._plans, key=str.lower):
            original_name = get_original_name(path)
            original = os.path.join(os.path.dirname(path), f"{original_name}.als") \
                if original_name else None
            if original is not None and original in self._plans:
                self._versions.setdefault(original, []).append(path)
                self._originals[path] = original
            else:
                top_level.append(path)

        self.projects_item = TreeItem(format_path(self.project_path), expanded=True, flagged=True,
                                      path=self.project_path, children=[self._build_project_item(path) for path in top_level])
        self.patches_item = TreeItem("Patches", children=[item for _, item in self._patch_items], expanded=True,
                                     flagged=True, details=self._get_patches_details)
        self.root = TreeItem("VST2 to VST3 conversion", children=[self.projects_item, self.patches_item],
                             expanded=True, flagged=True, details=self._get_summary_details)
        self.refresh()
        return self.root

    def get_actions(self) -> List[BrowserAction]:
        return [BrowserAction("c", "convert", self._convert, applies=lambda item: self._get_project(item) is not None,
                              busy_message="Converting... (this can take a while for big projects)"),
                BrowserAction("m", "switch mode", self._switch_mode)]

    def refresh(self):
        """Updates every status and note, e.g. after the mode changed or a patch was ticked."""
        for path, item in self._project_items.items():
            self._update_project_item(path, item)
        for path, plugin_items in self._plugin_items.items():
            for name, plugin_item in plugin_items:
                self._update_plugin_item(path, name, plugin_item)
        for patch, patch_item in self._patch_items:
            source = self._patch_sources[id(patch)]
            names = self._get_patched_plugins(patch)
            patch_item.note = f"{source} · " + \
                (f"for {_describe_names(names)}" if names else "not needed")

        projects = self.projects_item.children
        to_convert = len([item for item in projects if item.flagged])
        converted = len([item for item in projects
                         if item.path in self._versions])
        self.projects_item.note = f"{pluralize(len(projects), 'project')} · {to_convert:,} to convert · {converted:,} converted"
        ticked = len([item for _, item in self._patch_items if item.checked])
        self.patches_item.note = f"{ticked:,} of {len(self._patch_items):,} ticked"
        self.root.note = f"mode: {self.options.mode}"

    def _build_project_item(self, path: str) -> TreeItem:
        plan = self._plans[path]
        plugin_items: List[Tuple[str, TreeItem]] = []
        for name in sorted({plugin.name for plugin in plan.plugins}, key=str.lower):
            count = len([plugin for plugin in plan.plugins
                         if plugin.name == name])
            plugin_item = TreeItem(name + (f" ×{count}" if count > 1 else ""), flagged=True,
                                   details=lambda name=name: self._get_plugin_details(path, name))
            self._plugin_projects[id(plugin_item)] = path
            plugin_items.append((name, plugin_item))
        self._plugin_items[path] = plugin_items

        item = TreeItem(self._get_project_name(path), path=path,
                        details=lambda: self._get_project_details(path))
        item.children = [plugin_item for _, plugin_item in plugin_items] + \
            [self._build_project_item(version)
             for version in self._versions.get(path, [])]
        self._project_items[path] = item
        return item

    def _update_project_item(self, path: str, item: TreeItem):
        plan = self._plans[path]
        item.flagged = False
        if plan.error is not None:
            item.status, item.style, item.note = "unreadable", Style.RED, plan.error
            return

        counts = plan.count(self.options.mode)
        versions = self._versions.get(path, [])
        notes: List[str] = []
        if len(versions) > 0:
            notes.append(pluralize(len(versions), "converted version"))
        if counts[PluginStatus.CONVERT] > 0:
            notes.append(
                "converts " + _describe_names(self._get_plugin_names(plan, PluginStatus.CONVERT)))
        notes += [f"{counts[status]:,} {STATUS_COUNTS[status]}" for status in STATUS_COUNTS
                  if status != PluginStatus.CONVERT and counts[status] > 0]
        if len(plan.plugins) == 0:
            notes.append(pluralize(plan.vst3_count, "VST3 plugin"))
        item.note = " · ".join(notes)

        if path in self._originals:
            # this is a converted version of another project
            item.status, item.style = ("all VST3", Style.GREEN) if len(plan.plugins) == 0 else \
                ("VST2 left", Style.DIM)
        elif len(versions) > 0:
            item.status, item.style = "converted", Style.GREEN
        elif counts[PluginStatus.CONVERT] > 0:
            # flagged projects are the ones shown when only projects to convert are shown
            item.status, item.style = "to convert", Style.YELLOW
            item.flagged = True
        elif len(plan.plugins) == 0:
            item.status, item.style = "no VST2", Style.DIM
        else:
            item.status, item.style = "nothing to do", Style.DIM

    def _update_plugin_item(self, path: str, name: str, item: TreeItem):
        plugins = self._get_plugins(path, name)
        statuses = {plugin.get_status(self.options.mode)
                    for plugin in plugins}
        if len(statuses) > 1:
            # instances of the same plugin can end up differently, e.g. if one of them has broken data
            item.status, item.style = "mixed", Style.YELLOW
            item.note = ", ".join(f"{len([plugin for plugin in plugins if plugin.get_status(self.options.mode) == status]):,} "
                                  f"{STATUS_COUNTS[status]}" for status in STATUS_COUNTS if status in statuses)
            return

        status = statuses.pop()
        item.status, item.style = STATUS_LABELS[status]
        plugin = plugins[0]
        if status == PluginStatus.CONVERT:
            item.note = f"→ {plugin.vst3_name}"
            patches = self._get_patches(plugin, ticked_only=True)
            if len(patches) == 1:
                item.note += f" · patch: {patches[0].name}"
            elif len(patches) > 1:
                item.status, item.style = "patch clash", Style.RED
                item.note += f" · {len(patches)} ticked patches apply, untick all but one"
        elif status == PluginStatus.INSTALLED:
            item.note = "stays VST2 in 'necessary' mode"
        elif status == PluginStatus.KEPT:
            item.note = "no VST3 version, so the installed VST2 is kept" if plugin.error is None else \
                "can't be converted, so the installed VST2 is kept"
        elif status == PluginStatus.NO_VST3:
            item.note = "no matching VST3 plugin is installed"
        elif status == PluginStatus.IGNORED:
            item.note = "excluded by --include-plugins or --ignore-plugins"
        else:
            item.note = plugin.error or ""

    def _convert(self, item: TreeItem) -> str:
        path = self._get_project(item)
        assert path is not None
        plan = self._plans[path]
        name = os.path.basename(path)
        if plan.error is not None:
            return f"'{name}' could not be read, so it can't be converted."

        counts = plan.count(self.options.mode)
        if counts[PluginStatus.CONVERT] == 0:
            hint = " Press m to convert installed plugins too." \
                if self.options.mode == ConversionMode.NECESSARY and counts[PluginStatus.INSTALLED] > 0 else ""
            return f"Nothing to convert in '{name}' in '{self.options.mode}' mode.{hint}"

        patches = [patch for patch, patch_item in self._patch_items
                   if patch_item.checked]
        with _capture_logs() as records:
            try:
                result = convert_project(
                    Path(path), self.db, PatchRegistry(patches), self.options)
            except Exception as e:
                return f"Could not convert '{name}'. Error: {e}"
        self._logs[path] = records

        failed = f", {len(result.failed):,} failed (the details show why)" if len(
            result.failed) > 0 else ""
        if result.path is None:
            return f"No plugins could be converted{failed}, so no file was written."

        converted_path = str(result.path)
        self._plans[converted_path] = plan_project_file(
            converted_path, self.options)
        self._logs[converted_path] = records
        self._originals[converted_path] = path
        self._versions.setdefault(path, []).append(converted_path)
        project_item = self._project_items[path]
        project_item.children.append(
            self._build_project_item(converted_path))
        project_item.expanded = True
        self.refresh()
        unconvertible = counts[PluginStatus.NO_VST3] + \
            counts[PluginStatus.ERROR]
        left = f" {unconvertible:,} can't be converted and stay VST2." if unconvertible > 0 else ""
        if len(result.kept) > 0:
            left += f" Kept {pluralize(len(result.kept), 'installed VST2 plugin')} that can't be converted."
        return f"Converted {pluralize(len(result.converted), 'plugin')}{failed}. Saved as '{result.path.name}'.{left}"

    def _switch_mode(self, item: TreeItem) -> str:
        if self.options.mode == ConversionMode.NECESSARY:
            self.options.mode = ConversionMode.ALL
            message = "Switched to 'all' mode: every VST2 plugin with a VST3 version is converted."
        else:
            self.options.mode = ConversionMode.NECESSARY
            message = "Switched to 'necessary' mode: only VST2 plugins that aren't installed are converted."
        self.refresh()
        return message

    def _get_project_details(self, path: str) -> List[DetailLine]:
        plan = self._plans[path]
        mode = self.options.mode
        lines: List[DetailLine] = [
            (format_path(path), Style.BOLD), ("", Style.DEFAULT)]
        if plan.error is not None:
            lines.append(
                (f"This project could not be read. Error: {plan.error}", Style.RED))
            return lines

        original = self._originals.get(path)
        if original is not None:
            lines.append(
                (f"Converted from {os.path.basename(original)}.", Style.DEFAULT))

        counts = plan.count(mode)
        if len(plan.plugins) == 0:
            lines.append(
                ("This project has no VST2 plugins, so there is nothing to convert.", Style.DEFAULT))
        elif counts[PluginStatus.CONVERT] == 0:
            lines.append(
                (f"Nothing will be converted in '{mode}' mode.", Style.DEFAULT))
        else:
            lines.append((f"Pressing c converts {counts[PluginStatus.CONVERT]:,} of the {pluralize(len(plan.plugins), 'VST2 plugin')} "
                          f"in '{mode}' mode and saves the result next to this project. This project is not changed.", Style.DEFAULT))

        for status, heading in STATUS_HEADINGS.items():
            names = self._get_plugin_names(plan, status)
            if len(names) == 0:
                continue
            lines += [("", Style.DEFAULT),
                      (f"{heading} ({counts[status]:,})", Style.BOLD)]
            for name in names:
                plugins = [plugin for plugin in self._get_plugins(path, name)
                           if plugin.get_status(mode) == status]
                text = f"  {name}" + \
                    (f" ×{len(plugins)}" if len(plugins) > 1 else "")
                if status == PluginStatus.CONVERT:
                    text += f" → {plugins[0].vst3_name}"
                elif status == PluginStatus.ERROR:
                    text += f": {plugins[0].error}"
                lines.append((text, STATUS_LABELS[status][1] if status in (
                    PluginStatus.NO_VST3, PluginStatus.ERROR) else Style.DEFAULT))
        lines += [("", Style.DEFAULT),
                  (f"VST3 plugins already in this project: {plan.vst3_count:,}", Style.DEFAULT)]

        versions = self._versions.get(path, [])
        if len(versions) > 0:
            lines += [("", Style.DEFAULT),
                      (f"Converted versions ({len(versions):,})", Style.BOLD)]
            lines += [(f"  {os.path.basename(version)}", Style.DEFAULT)
                      for version in versions]

        records = self._logs.get(path)
        if records is not None:
            lines += [("", Style.DEFAULT),
                      ("Log of the last conversion", Style.BOLD)]
            lines += [(f"  {record.getMessage()}", Style.RED if record.levelno >= logging.ERROR else Style.DIM)
                      for record in records]
        return lines

    def _get_plugin_details(self, path: str, name: str) -> List[DetailLine]:
        plugins = self._get_plugins(path, name)
        plugin = plugins[0]
        lines: List[DetailLine] = [(name, Style.BOLD), ("", Style.DEFAULT),
                                   (f"Used {pluralize(len(plugins), 'time')} in {os.path.basename(path)}.", Style.DEFAULT)]
        if "plugin_vendor" in plugin.metadata:
            lines.append(
                (f"Vendor: {plugin.metadata['plugin_vendor']}", Style.DEFAULT))
        lines.append(
            (f"VST2 version installed: {'yes' if plugin.installed else 'no'}", Style.DEFAULT))
        lines.append(
            (f"Matching VST3 plugin: {plugin.vst3_name or 'none found'}", Style.DEFAULT))

        lines.append(("", Style.DEFAULT))
        explanations = {
            PluginStatus.CONVERT: "It will be replaced by the VST3 version.",
            PluginStatus.INSTALLED: "The VST2 version is installed, so 'necessary' mode leaves it alone. Press m to switch to 'all' mode.",
            PluginStatus.KEPT: "There is no VST3 version to convert it to (or its data can't be converted), but the VST2 version "
                               "is installed, so it is kept as it is.",
            PluginStatus.NO_VST3: "It can't be converted because no matching VST3 plugin is installed.",
            PluginStatus.IGNORED: "It is excluded by --include-plugins or --ignore-plugins.",
            PluginStatus.ERROR: "It can't be converted, e.g. because the project was made in an older version of Live.",
        }
        for status in sorted({plugin.get_status(self.options.mode) for plugin in plugins}, key=lambda status: status.value):
            lines.append((explanations[status], STATUS_LABELS[status][1]))
        lines += [(f"  {error}", Style.RED)
                  for error in sorted({plugin.error for plugin in plugins if plugin.error})]

        patches = self._get_patches(plugin, ticked_only=False)
        lines += [("", Style.DEFAULT), ("Patches", Style.BOLD)]
        if len(patches) == 0:
            lines.append(
                ("  No patches apply to this plugin, so its data is copied over unchanged.", Style.DEFAULT))
        for patch in patches:
            checked = self._is_ticked(patch)
            lines.append((f"  {'[x]' if checked else '[ ]'} {patch.name}" +
                          ("" if checked else " (unticked, so it won't be used)"), Style.DEFAULT))
        return lines

    def _get_patch_details(self, patch: PluginPatch, source: str) -> List[DetailLine]:
        lines: List[DetailLine] = [(patch.name, Style.BOLD), ("", Style.DEFAULT),
                                   (f"Source: {source}", Style.DEFAULT)]
        description = type(patch).__doc__
        if description:
            lines.append((" ".join(description.split()), Style.DEFAULT))

        lines += [("", Style.DEFAULT),
                  (f"Needed for these plugins in '{self.options.mode}' mode", Style.BOLD)]
        names = self._get_patched_plugins(patch)
        if len(names) == 0:
            lines.append(
                ("  None of the plugins that would be converted need this patch.", Style.DEFAULT))
        for name in names:
            projects = {plan.path for plan in self._plans.values() for plugin in plan.plugins
                        if plugin.name == name and self._patch_applies(patch, plugin)}
            lines.append(
                (f"  {name}  ({pluralize(len(projects), 'project')})", Style.DEFAULT))

        state = "ticked, so it is used" if self._is_ticked(
            patch) else "unticked, so it is not used"
        lines += [("", Style.DEFAULT),
                  (f"This patch is {state} when converting. Press space or → to change that.", Style.DIM)]
        return lines

    def _get_patches_details(self) -> List[DetailLine]:
        return [("Patches", Style.BOLD), ("", Style.DEFAULT),
                ("Patches convert the data of plugins that store their settings differently in VST2 and VST3. "
                 "Only ticked patches are used, and at most one patch may apply to each plugin.", Style.DEFAULT),
                ("Add your own patches with --patch-dir.", Style.DIM)]

    def _get_summary_details(self) -> List[DetailLine]:
        return [("VST2 to VST3 conversion", Style.BOLD), ("", Style.DEFAULT),
                (f"Mode: {self.options.mode}. Press m to switch between 'necessary' mode (only convert VST2 plugins that "
                 "aren't installed) and 'all' mode (convert every VST2 plugin that has a VST3 version).", Style.DEFAULT),
                ("Expand a project to see what will happen to each of its plugins, then press c to convert it. "
                 "Converted projects are saved next to the original and listed inside it.", Style.DEFAULT),
                ("Tick the patches to use under 'Patches' with space or →.", Style.DEFAULT)]

    def _get_project(self, item: TreeItem) -> Optional[str]:
        """Returns the project file that an item belongs to, if any."""
        if item.path in self._plans:
            return item.path
        return self._plugin_projects.get(id(item))

    def _get_project_name(self, path: str) -> str:
        if path in self._originals:
            return os.path.basename(path)
        if os.path.isfile(self.project_path):
            return os.path.basename(path)
        return os.path.relpath(path, self.project_path)

    def _get_plugins(self, path: str, name: str) -> List[PluginPlan]:
        return [plugin for plugin in self._plans[path].plugins if plugin.name == name]

    def _get_plugin_names(self, plan: ProjectPlan, status: PluginStatus) -> List[str]:
        return sorted({plugin.name for plugin in plan.plugins
                       if plugin.get_status(self.options.mode) == status}, key=str.lower)

    def _get_patches(self, plugin: PluginPlan, ticked_only: bool) -> List[PluginPatch]:
        return [patch for patch, item in self._patch_items
                if (item.checked or not ticked_only) and self._patch_applies(patch, plugin)]

    def _get_patched_plugins(self, patch: PluginPatch) -> List[str]:
        """Returns the names of the plugins that will be converted and that the patch applies to."""
        return sorted({plugin.name for plan in self._plans.values() for plugin in plan.plugins
                       if plugin.get_status(self.options.mode) == PluginStatus.CONVERT and self._patch_applies(patch, plugin)},
                      key=str.lower)

    def _patch_applies(self, patch: PluginPatch, plugin: PluginPlan) -> bool:
        # patches only get to see plugins that have a VST3 version
        if plugin.vst3_name is None:
            return False
        try:
            return patch.should_apply(plugin.metadata)
        except Exception:
            # user patches may expect data that isn't there
            return False

    def _is_ticked(self, patch: PluginPatch) -> bool:
        return any(item.checked for other, item in self._patch_items if other is patch)


def _describe_names(names: Iterable[str]) -> str:
    """Lists some names, e.g. 'Serum, Pro-Q 3 +2 more'."""
    unique = sorted(set(names), key=str.lower)
    if len(unique) <= MAX_LISTED_PLUGINS:
        return ", ".join(unique)
    shown = MAX_LISTED_PLUGINS - 1
    return ", ".join(unique[:shown]) + f" +{len(unique) - shown} more"


class _LogCollector(logging.Handler):
    def __init__(self, records: List[logging.LogRecord]):
        super().__init__()
        self.records = records

    def emit(self, record: logging.LogRecord):
        self.records.append(record)


@contextmanager
def _capture_logs() -> Iterator[List[logging.LogRecord]]:
    """Collects log messages instead of printing them, so that they don't mess up the tree browser."""
    records: List[logging.LogRecord] = []
    logger = logging.getLogger()
    handlers = logger.handlers[:]
    logger.handlers = [_LogCollector(records)]
    try:
        yield records
    finally:
        logger.handlers = handlers
