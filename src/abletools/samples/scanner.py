import logging
import os
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set

from abletools.samples.projects import Project
from abletools.samples.samples import Sample, is_media_file, should_ignore


class UsageType(Enum):
    # no files in this directory or files in subdirectories are used in any project
    UNUSED = auto()
    TRANSITIVE = auto()  # some subdirectory is marked as USED
    USED = auto()  # a direct child (file) in this directory is used in some project


@dataclass
class Node:
    # the absolute path of this directory
    path: str = field()
    # whether or not this directory has any used samples
    usage: UsageType = field()
    # the subdirectories of this directory
    children: List["Node"] = field(default_factory=lambda: [])
    # the samples directly inside this directory
    samples: List[Sample] = field(default_factory=lambda: [])
    # the number of samples in this directory and its subdirectories
    sample_count: int = field(default=0)
    # the size in bytes of the samples in this directory and its subdirectories
    size: int = field(default=0)
    # the project files that use samples in this directory or its subdirectories
    projects: Set[str] = field(default_factory=lambda: set())


@dataclass
class ScanResult:
    root: Node = field()
    # the projects that were scanned
    projects: List[Project] = field()
    # the project files that use each sample
    usages: Dict[Sample, Set[str]] = field()


class Scanner:
    _result: Optional[ScanResult] = None

    def scan(self, projects: List[Project], sample_folder: str, recursive: bool):
        usages = get_usages(projects)
        root = self._find_unused_samples(
            os.path.abspath(sample_folder), usages, recursive)
        self._result = ScanResult(root, projects, usages)

    def _find_unused_samples(self, folder: str, usages: Dict[Sample, Set[str]], recursive: bool) -> Node:
        res = Node(folder, UsageType.UNUSED)
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda entry: entry.name.lower())
        except OSError as e:
            logging.warning(f"Could not scan folder '{folder}'. Error: {e}")
            return res

        for entry in entries:
            if entry.is_dir() and recursive:
                child = self._find_unused_samples(
                    entry.path, usages, recursive)
                if res.usage != UsageType.USED and child.usage in (UsageType.USED, UsageType.TRANSITIVE):
                    res.usage = UsageType.TRANSITIVE
                res.sample_count += child.sample_count
                res.size += child.size
                res.projects.update(child.projects)
                res.children.append(child)
            elif entry.is_file() and is_media_file(entry.name) and not should_ignore(entry.name):
                sample = Sample(entry.path)
                res.samples.append(sample)
                res.sample_count += 1
                res.size += entry.stat().st_size
                if sample in usages:
                    res.usage = UsageType.USED
                    res.projects.update(usages[sample])
        return res

    @property
    def result(self) -> ScanResult:
        if self._result is None:
            raise RuntimeError(
                "Cannot access 'result' before running 'scan()'.")
        return self._result


def get_usages(projects: List[Project]) -> Dict[Sample, Set[str]]:
    """Returns the project files that use each sample."""
    usages: Dict[Sample, Set[str]] = {}
    for project in projects:
        for sample in project.samples:
            usages.setdefault(sample, set()).add(project.path)
    return usages


def find_unused_folders(node: Node) -> List[Node]:
    """Returns the unused folders that are not inside another unused folder."""
    if node.usage == UsageType.UNUSED:
        return [node]
    return [unused for child in node.children for unused in find_unused_folders(child)]
