from argparse import Namespace
from pathlib import Path


from abletools.utils import project_utils


def unpack_project(args: Namespace):
    project_path = Path(args.projfile)

    with open(project_path.with_suffix(".xml"), "wb") as f:
        contents = project_utils.read_project_file(project_path)
        f.write(contents)


def pack_project(args: Namespace):
    project_path = Path(args.projfile)
    packed_path = project_path.with_suffix(
        project_utils.ABLETON_LIVE_PROJECT_SUFFIX)

    if packed_path.exists():
        counter = 1
        base_path = packed_path
        while packed_path.exists():
            packed_path = base_path.with_name(
                f"{base_path.stem} {counter}{base_path.suffix}")
            counter += 1

    project_utils.write_project_file(
        packed_path, project_utils.read_project_file(project_path))
