import html
import os
import re


from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Collection, List, Optional, Set


from abletools.samples.samples import Sample
from abletools.utils import project_utils
from abletools.utils.process_utils import map_in_processes

# pre-compile regex
# the file reference of a sample, e.g. <SampleRef Id="1"><FileRef>...</FileRef>
SAMPLE_REF_PATTERN = re.compile(
    r'<SampleRef(?: [^>]*)?>\s*<FileRef(?: [^>]*)?>(.*?)</FileRef>', re.DOTALL)
# Live 11 and later store the whole path, e.g. <Path Value="/Users/me/Samples/Kick.wav" />
PATH_PATTERN = re.compile(r'<Path Value="([^"]*)"')
# Live 10 and earlier store the folders of the path and the file name separately
PATH_HINT_PATTERN = re.compile(r'<PathHint>(.*?)</PathHint>', re.DOTALL)
RELATIVE_PATH_PATTERN = re.compile(
    r'<RelativePath>(.*?)</RelativePath>', re.DOTALL)
FOLDER_PATTERN = re.compile(r'<RelativePathElement [^>]*Dir="([^"]*)"')
NAME_PATTERN = re.compile(r'<Name Value="([^"]*)"')


class DirType(Enum):
    DEFAULT = auto()  # this folder contains nothing of interest but may contain project folders
    PROJECT = auto()  # this folder contains project files which should be scanned
    BACKUP = auto()  # this folder contains backups which may be skipped


@dataclass
class Project:
    # the absolute path of the project file
    path: str = field()
    # the samples used in the project
    samples: Set[Sample] = field(default_factory=lambda: set())
    # why the project file could not be read, if it could not be read
    error: Optional[str] = field(default=None)


def read_projects(project_files: Collection[str], on_process: Optional[Callable[[int, int], None]] = None) -> List[Project]:
    """Reads the samples used in each project file, using all CPU cores.

    :param on_process: Called after each project file is read with (project_index, project_count).
    """
    return map_in_processes(read_project, project_files, on_process)


def read_project(path: str) -> Project:
    """
    Retrieves all samples used in a given project file.
    """
    path = os.path.abspath(path)
    try:
        contents = project_utils.read_project_file(Path(path)).decode()
    except Exception as e:
        # this runs in a worker process, so report the error instead of raising it
        return Project(path, error=str(e))

    project_folder = get_project_folder(path)
    samples: Set[Sample] = set()
    for file_ref in SAMPLE_REF_PATTERN.findall(contents):
        sample_path = _get_sample_path(file_ref, project_folder)
        if sample_path is not None:
            # ensure that paths are absolute
            samples.add(Sample(os.path.abspath(sample_path)))
    return Project(path, samples)


def find_project_files(path: str, recursive: bool, include_backups: bool) -> set[str]:
    """Returns the project files in a folder, or the project file itself if the path is a file."""
    if os.path.isfile(path):
        return {path} if is_project_file(path) else set()
    return get_project_files(path, recursive, include_backups)


def get_project_folder(project_file: str) -> str:
    """Returns the folder that a project's relative sample paths start from.

    This is the folder containing the project file, unless the project file is a backup.
    """
    folder = os.path.dirname(os.path.abspath(project_file))
    return os.path.dirname(folder) if is_backup_dir(folder) else folder


def is_project_file(file: str) -> bool:
    return file.lower().endswith(".als")


def is_project_dir(folder: str) -> bool:
    return any(is_project_file(child) for child in os.listdir(folder))


def is_backup_dir(folder: str) -> bool:
    return os.path.basename(folder) == "Backup"


def get_project_files(folder: str, recursive: bool, include_backups: bool, dir_type: DirType = DirType.DEFAULT) -> set[str]:
    # functions somewhat like a state machine
    # all directories are marked as DirType.DEFAULT by default
    # if a default directory has at least one project file then it is marked as DirType.PROJECT
    # if a directory inside a DirType.PROJECT directory is called 'Backup' then it is marked as DirType.BACKUP
    # DirType.BACKUP is skipped if backups are not included

    project_files: Set[str] = set()
    if dir_type is DirType.BACKUP and not include_backups:
        return project_files

    children = os.listdir(folder)

    if dir_type is DirType.DEFAULT and is_project_dir(folder):
        dir_type = DirType.PROJECT

    for child in children:
        file = os.path.join(folder, child)
        if recursive and os.path.isdir(file):
            sub_dir_type = DirType.BACKUP if dir_type is DirType.PROJECT and is_backup_dir(
                file) else DirType.DEFAULT

            project_files.update(get_project_files(
                file, recursive, include_backups, sub_dir_type))
        elif os.path.isfile(file) and is_project_file(file):
            project_files.add(file)
    return project_files


def _get_sample_path(file_ref: str, project_folder: str) -> Optional[str]:
    # Live escapes characters like '&' in paths (&amp;) so they have to be unescaped
    path = PATH_PATTERN.search(file_ref)
    if path is not None:
        if not path.group(1):
            return None
        # the path may be relative to the project folder, e.g. 'Samples/Recorded/Audio 1.wav'
        return os.path.join(project_folder, html.unescape(path.group(1)))

    name = NAME_PATTERN.search(file_ref)
    if name is None:
        return None
    name = html.unescape(name.group(1))

    # the path hint holds the absolute path of the folder containing the sample
    path_hint = PATH_HINT_PATTERN.search(file_ref)
    folders = _get_folders(path_hint.group(1)) if path_hint else []
    if len(folders) > 0:
        # on Windows the first folder is the drive, e.g. 'C:'
        root = "" if folders[0].endswith(":") else os.sep
        return root + os.sep.join(folders + [name])

    # otherwise the path is relative to the project folder, where empty folder names mean "go up a folder"
    relative_path = RELATIVE_PATH_PATTERN.search(file_ref)
    if relative_path is None:
        return None
    folders = [folder or os.pardir
               for folder in _get_folders(relative_path.group(1))]
    return os.path.join(project_folder, *folders, name)


def _get_folders(path_elements: str) -> List[str]:
    return [html.unescape(folder) for folder in FOLDER_PATTERN.findall(path_elements)]
