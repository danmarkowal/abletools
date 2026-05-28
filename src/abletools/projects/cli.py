from argparse import Namespace
from pathlib import Path


from abletools.utils import project_utils


def unpack_project(args: Namespace):
    project_path = Path(args.projfile)

    with open(project_path.with_suffix(".xml"), "wb") as f:
        contents = project_utils.read_project_file(project_path)
        f.write(contents)


def pack_project(args: Namespace):
    pass
