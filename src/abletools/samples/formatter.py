import os


from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set


from abletools.samples.projects import Project, get_project_folder
from abletools.samples.samples import Sample
from abletools.samples.scanner import Node, ScanResult, UsageType, get_usages
from abletools.utils.tree import DetailLine, TreeItem
from abletools.utils.tui_utils import Style, format_path, format_size, pluralize


# how many project names a note lists before it shortens the rest to '+3 more'
MAX_LISTED_PROJECTS = 3


class Formatter:
    def __init__(self, project_path: str):
        self.project_path = os.path.abspath(project_path)

    def _get_project_name(self, project_file: str) -> str:
        """Returns the path of a project file relative to the scanned folder, e.g. 'Song Project/Song.als'."""
        if os.path.isfile(self.project_path):
            return os.path.basename(project_file)
        return os.path.relpath(project_file, self.project_path)

    def _describe_projects(self, project_files: Iterable[str]) -> str:
        """Lists the names of some projects, e.g. 'Song A, Song B +3 more'."""
        names = sorted((Path(file).stem for file in project_files),
                       key=str.lower)
        if len(names) <= MAX_LISTED_PROJECTS:
            return ", ".join(names)
        shown = MAX_LISTED_PROJECTS - 1
        return ", ".join(names[:shown]) + f" +{len(names) - shown} more"

    def _get_project_lines(self, project_files: Iterable[str], indent: str = "  ") -> List[DetailLine]:
        return [(indent + self._get_project_name(file), Style.DEFAULT)
                for file in sorted(project_files, key=str.lower)]


class FolderFormatter(Formatter):
    """Builds a tree of sample folders that shows which folders are used and why."""

    def __init__(self, result: ScanResult, project_path: str):
        super().__init__(project_path)
        self.result = result
        self.project_count = len(
            [project for project in result.projects if project.error is None])

    def build(self) -> TreeItem:
        root = self._build_item(self.result.root,
                                format_path(self.result.root.path) + os.sep)
        root.expanded = True
        return root

    def _build_item(self, node: Node, name: str) -> TreeItem:
        children = [self._build_item(child, os.path.basename(child.path) + os.sep)
                    for child in node.children]
        is_unused = node.usage == UsageType.UNUSED
        contains_unused = is_unused or any(child.flagged for child in children)

        item = TreeItem(name, children=children, path=node.path,
                        details=lambda: self._get_details(node))
        # flagged folders are the ones shown when only unused folders are shown
        item.flagged = contains_unused
        # unused folders start off collapsed since everything inside them is unused too
        item.expanded = contains_unused and not is_unused

        if is_unused:
            item.status = "unused"
            item.style = Style.YELLOW
            item.note = "no samples" if node.sample_count == 0 else \
                f"{pluralize(node.sample_count, 'sample')} · {format_size(node.size)}"
        elif node.usage == UsageType.USED:
            used_samples = self._get_used_samples(node)
            item.status = "used"
            item.style = Style.GREEN
            item.note = f"{len(used_samples):,} of {pluralize(len(node.samples), 'sample')} · " + \
                self._describe_projects(self._get_direct_projects(node))
        else:
            item.status = "used"
            item.style = Style.GREEN
            item.note = "via subfolders · " + \
                self._describe_projects(node.projects)
        return item

    def _get_details(self, node: Node) -> List[DetailLine]:
        lines: List[DetailLine] = [
            (format_path(node.path) + os.sep, Style.BOLD), ("", Style.DEFAULT)]

        if node.usage == UsageType.UNUSED:
            projects = f"any of the {pluralize(self.project_count, 'project')} that were scanned"
            if node.sample_count == 0:
                reason = "there are no samples in this folder or its subfolders."
            elif node.sample_count == 1:
                reason = f"the only sample in this folder or its subfolders is not used by {projects}."
            else:
                reason = f"none of the {pluralize(node.sample_count, 'sample')} in this folder or its subfolders are used by {projects}."
            lines.append(("Unused: " + reason, Style.YELLOW))
            lines.append((f"Size: {format_size(node.size)}", Style.DEFAULT))
            return lines

        used_samples = self._get_used_samples(node)
        if node.usage == UsageType.USED:
            verb = "is" if len(used_samples) == 1 else "are"
            lines.append((f"Used: {len(used_samples):,} of {pluralize(len(node.samples), 'sample')} in this folder {verb} used "
                          f"in {pluralize(len(self._get_direct_projects(node)), 'project')}.", Style.GREEN))
        else:
            lines.append(("Used: none of the samples directly inside this folder are used, "
                          "but samples in its subfolders are.", Style.GREEN))

        if len(used_samples) > 0:
            lines += [("", Style.DEFAULT),
                      ("Used samples in this folder", Style.BOLD)]
            for sample in used_samples:
                lines.append(
                    ("  " + os.path.basename(sample.path), Style.DEFAULT))
                lines += [(text, Style.DIM) for text, _ in self._get_project_lines(
                    self.result.usages[sample], indent="    ")]

        used_children = [child for child in node.children
                         if child.usage != UsageType.UNUSED]
        if len(used_children) > 0:
            lines += [("", Style.DEFAULT), ("Used subfolders", Style.BOLD)]
            for child in used_children:
                lines.append((f"  {os.path.basename(child.path)}{os.sep}  "
                              f"({pluralize(len(child.projects), 'project')})", Style.DEFAULT))

        lines += [("", Style.DEFAULT),
                  (f"Projects that use samples in this folder or its subfolders ({len(node.projects):,})", Style.BOLD)]
        lines += self._get_project_lines(node.projects)
        return lines

    def _get_used_samples(self, node: Node) -> List[Sample]:
        return [sample for sample in node.samples if sample in self.result.usages]

    def _get_direct_projects(self, node: Node) -> Set[str]:
        """Returns the projects that use samples directly inside a folder (not in its subfolders)."""
        return {project for sample in self._get_used_samples(node)
                for project in self.result.usages[sample]}


class UsageFormatter(Formatter):
    """Builds trees that show which samples are used in which projects."""

    def __init__(self, projects: List[Project], project_path: str, sample_folder: Optional[str]):
        super().__init__(project_path)
        self.sample_folder = os.path.abspath(
            sample_folder) if sample_folder else None
        self.projects = sorted((project for project in projects if project.error is None),
                               key=lambda project: project.path.lower())
        # only the samples inside the sample folder are shown, if one was given
        self.samples: Dict[str, List[Sample]] = {
            project.path: sorted((sample for sample in project.samples if self._is_shown(sample)),
                                 key=lambda sample: sample.path.lower())
            for project in self.projects}
        self.usages = get_usages(self.projects)

    def build_by_project(self, expanded: bool) -> TreeItem:
        """Builds a tree of projects, each containing the samples it uses."""
        items = [self._build_project_item(project, expanded)
                 for project in self.projects if len(self.samples[project.path]) > 0]
        # a single project file doesn't need a folder around it
        if os.path.isfile(self.project_path) and len(items) == 1:
            items[0].name = format_path(self.project_path)
            items[0].expanded = True
            return items[0]

        if self.sample_folder:
            note = f"{len(items):,} of {pluralize(len(self.projects), 'project')} use samples from {format_path(self.sample_folder)}"
        else:
            note = pluralize(len(self.projects), "project")
        return TreeItem(format_path(self.project_path), note=note, children=items, expanded=True,
                        path=self.project_path, details=lambda: self._get_summary_details(len(items)))

    def build_by_sample(self, expanded: bool) -> TreeItem:
        """Builds a tree of samples, each containing the projects that use it."""
        samples = sorted((sample for sample in self.usages if self._is_shown(sample)),
                         key=lambda sample: sample.path.lower())
        items = [self._build_sample_item(sample, expanded)
                 for sample in samples]
        project_count = len({project for sample in samples
                             for project in self.usages[sample]})

        name = format_path(self.sample_folder) + \
            os.sep if self.sample_folder else "All samples"
        note = f"{pluralize(len(items), 'sample')} used in {pluralize(project_count, 'project')}"
        return TreeItem(name, note=note, children=items, expanded=True, path=self.sample_folder,
                        details=lambda: self._get_summary_details(project_count))

    def _build_project_item(self, project: Project, expanded: bool) -> TreeItem:
        samples = self.samples[project.path]
        children = [TreeItem(self._get_sample_name(sample, project), path=sample.path,
                             details=lambda sample=sample: self._get_sample_details(sample))
                    for sample in samples]
        return TreeItem(self._get_project_name(project.path), note=pluralize(len(samples), "sample"),
                        children=children, expanded=expanded, path=project.path,
                        details=lambda: self._get_project_details(project))

    def _build_sample_item(self, sample: Sample, expanded: bool) -> TreeItem:
        project_files = sorted(self.usages[sample], key=str.lower)
        children = [TreeItem(self._get_project_name(file), path=file,
                             details=lambda file=file: self._get_project_details(self._find_project(file)))
                    for file in project_files]
        return TreeItem(self._get_sample_name(sample), note=pluralize(len(project_files), "project"),
                        children=children, expanded=expanded, path=sample.path,
                        details=lambda: self._get_sample_details(sample))

    def _get_summary_details(self, project_count: int) -> List[DetailLine]:
        sample_count = len([sample for sample in self.usages
                            if self._is_shown(sample)])
        lines: List[DetailLine] = [
            (format_path(self.project_path), Style.BOLD), ("", Style.DEFAULT)]
        if self.sample_folder:
            lines.append((f"{pluralize(project_count, 'project')} of the {len(self.projects):,} that were scanned "
                          f"use {pluralize(sample_count, 'sample')} from {format_path(self.sample_folder)}.", Style.DEFAULT))
        else:
            lines.append((f"{pluralize(len(self.projects), 'project')} use {pluralize(sample_count, 'sample')}.",
                          Style.DEFAULT))
        return lines

    def _get_project_details(self, project: Project) -> List[DetailLine]:
        samples = self.samples[project.path]
        lines: List[DetailLine] = [
            (format_path(project.path), Style.BOLD), ("", Style.DEFAULT)]
        source = f" from {format_path(self.sample_folder)}" if self.sample_folder else ""
        lines.append(
            (f"Uses {pluralize(len(samples), 'sample')}{source}.", Style.DEFAULT))

        # samples that no other project uses are the ones that matter when deciding what to keep
        only_here = [sample for sample in samples
                     if len(self.usages[sample]) == 1]
        if len(only_here) > 0:
            lines += [("", Style.DEFAULT),
                      (f"Only used in this project ({len(only_here):,})", Style.BOLD)]
            lines += [("  " + self._get_sample_name(sample, project), Style.DEFAULT)
                      for sample in only_here]
        return lines

    def _get_sample_details(self, sample: Sample) -> List[DetailLine]:
        lines: List[DetailLine] = [
            (format_path(sample.path), Style.BOLD), ("", Style.DEFAULT)]
        if os.path.isfile(sample.path):
            lines.append(
                (f"Size: {format_size(os.path.getsize(sample.path))}", Style.DEFAULT))
        else:
            lines.append(("This file no longer exists at this location. Live may still find it if it was moved, "
                          "e.g. if it belongs to an older version of Live's Core Library.", Style.YELLOW))

        project_files = self.usages[sample]
        lines += [("", Style.DEFAULT),
                  (f"Used in {pluralize(len(project_files), 'project')}", Style.BOLD)]
        lines += self._get_project_lines(project_files)
        return lines

    def _get_sample_name(self, sample: Sample, project: Optional[Project] = None) -> str:
        """Shortens the path of a sample to make it relative to the sample folder or the project folder, if it is inside one of them."""
        folders = [self.sample_folder,
                   get_project_folder(project.path) if project else None]
        for folder in folders:
            if folder is not None and _is_inside(sample.path, folder):
                return os.path.relpath(sample.path, folder)
        return format_path(sample.path)

    def _is_shown(self, sample: Sample) -> bool:
        return self.sample_folder is None or _is_inside(sample.path, self.sample_folder)

    def _find_project(self, project_file: str) -> Project:
        return next(project for project in self.projects if project.path == project_file)


def _is_inside(path: str, folder: str) -> bool:
    return path.startswith(folder.rstrip(os.sep) + os.sep)
