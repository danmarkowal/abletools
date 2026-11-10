from argparse import Namespace
from pathlib import Path


from abletools.utils import project_utils
from abletools.utils.cli_utils import Subparsers, add_command, file_type


def add_commands(subparsers: Subparsers):
    unpack_parser = add_command(
        subparsers, "unpack", unpack_project,
        help="Convert a project file (.als) to a readable XML file.",
        description="Converts an Ableton project file to a readable XML file next to it. An existing XML file with the same name is overwritten.",
        examples=["abletools unpack \"My Song.als\""])
    unpack_parser.add_argument(
        "projfile", type=file_type, help="The project file to unpack.")

    pack_parser = add_command(
        subparsers, "pack", pack_project,
        help="Convert an XML file back to a project file (.als).",
        description="Converts an XML file to an Ableton project file next to it. Existing project files are never overwritten.",
        examples=["abletools pack \"My Song.xml\""])
    pack_parser.add_argument("xmlfile", type=file_type,
                             help="The XML file to pack.")


def unpack_project(args: Namespace):
    project_path = Path(args.projfile)
    unpacked_path = project_path.with_suffix(".xml")

    with open(unpacked_path, "wb") as f:
        contents = project_utils.read_project_file(project_path)
        f.write(contents)

    print(f"Unpacked '{project_path}' to '{unpacked_path}'.")


def pack_project(args: Namespace):
    project_path = Path(args.xmlfile)
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

    print(f"Packed '{project_path}' to '{packed_path}'.")
