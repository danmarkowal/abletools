import os


import abletools.samples.cli as samples


from argparse import ArgumentParser
from typing import Optional, Sequence


def dir_path(arg: str):
    if os.path.isdir(arg):
        return arg
    else:
        raise NotADirectoryError(arg)


def main(argv: Optional[Sequence[str]] = None):
    parser = ArgumentParser(
        prog="abletools",
        description="CLI tools for Ableton Live.")
    subparsers = parser.add_subparsers(dest="commands", required=True)

    samples_parser = subparsers.add_parser(
        "alsamp", description="Finds unused samplepacks.")
    samples_parser.add_argument(
        "-p", "--projdir", type=dir_path, required=True)
    samples_parser.add_argument(
        "-s", "--sampledir", type=dir_path, required=True)
    samples_parser.add_argument("-r", "--recursive", action="store_false")
    samples_parser.add_argument("--debug", action="store_true")
    samples_parser.add_argument("--include-backups", action="store_true")
    samples_parser.set_defaults(func=samples.handle_command)

    try:
        args = parser.parse_args(argv)
    except NotADirectoryError as e:
        print(f"Folder not found: '{e}'.")
        return

    args.func(args)
