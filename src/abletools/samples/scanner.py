import os
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from multiprocessing import Pool
from typing import List, Optional, Set

from abletools.samples.projects import get_project_files, process_project_file
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


@dataclass
class ScanResult:
    root: Node = field()


class Scanner:
    _result: Optional[ScanResult] = None
    # on_process(project_index: int, project_count: int)
    on_process: Optional[Callable[[int, int], None]]

    def __init__(self, on_process: Optional[Callable[[int, int], None]] = None):
        self.on_process = on_process

    def scan(self, project_folder: str, sample_folder: str, recursive: bool, include_backups: bool):
        project_files = get_project_files(
            project_folder, recursive, include_backups)

        project_samples: Set[Sample] = set()
        hardware_concurrency = os.cpu_count()
        project_index = 0
        with Pool(processes=hardware_concurrency) as p:
            for result in p.imap_unordered(process_project_file, project_files):
                project_samples.update(result)
                project_index += 1
                # callback for progress bar
                if self.on_process is not None:
                    self.on_process(project_index, len(project_files))

        root = self._find_unused_samples(
            sample_folder, project_samples, recursive)
        self._result = ScanResult(root)

    def _find_unused_samples(self, folder: str, project_samples: set[Sample], recursive: bool) -> Node:
        res = Node(folder, UsageType.UNUSED, [])
        for child in os.listdir(folder):
            file = os.path.join(folder, child)
            if os.path.isdir(file) and recursive:
                child = self._find_unused_samples(
                    file, project_samples, recursive)
                if res.usage != UsageType.USED and child.usage in (UsageType.USED, UsageType.TRANSITIVE):
                    res.usage = UsageType.TRANSITIVE
                res.children.append(child)
            elif os.path.isfile(file) and is_media_file(file) and not should_ignore(file):
                sample = Sample(os.path.abspath(file))
                if sample in project_samples:
                    res.usage = UsageType.USED
        return res

    @property
    def result(self) -> ScanResult:
        if self._result is None:
            raise RuntimeError(
                "Cannot access 'result' before running 'scan()'.")
        return self._result
