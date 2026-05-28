import os
import re


import abletools.plugins.cli as plugins
import abletools.samples.cli as samples


from argparse import ArgumentParser, ArgumentTypeError
from typing import Optional, Sequence


def file_type(arg: str) -> str:
    if os.path.isfile(arg):
        return arg
    else:
        raise ArgumentTypeError(f"File not found: '{arg}'.")


def dir_type(arg: str) -> str:
    if os.path.isdir(arg):
        return arg
    else:
        raise ArgumentTypeError(f"Directory not found: '{arg}'.")


def regex_type(arg: str) -> re.Pattern[str]:
    try:
        return re.compile(arg)
    except re.error as e:
        raise ArgumentTypeError(
            f"Invalid regex pattern: '{arg}'. Error: {e}")


def main(argv: Optional[Sequence[str]] = None):
    parser = ArgumentParser(
        prog="abletools",
        description="CLI tools for Ableton Live.")
    subparsers = parser.add_subparsers(dest="commands", required=True)

    samples_parser = subparsers.add_parser(
        "samp", description="Finds unused samplepacks.")
    samples_parser.add_argument(
        "-p", "--projdir", type=dir_type, required=True, help="The directory containing your Ableton project folder(s).")
    samples_parser.add_argument(
        "-s", "--sampledir", type=dir_type, required=True, help="The directory containing your sample pack(s).")
    samples_parser.add_argument(
        "-r", "--recursive", action="store_false", help="Scan for project files recursively.")
    samples_parser.add_argument(
        "--debug", action="store_true", help="Print debug information.")
    samples_parser.add_argument("--include-backups", action="store_true",
                                help="Scan for samples in backup project folder.")
    samples_parser.set_defaults(func=samples.handle_command)

    plugins_parser = subparsers.add_parser(
        "plug", description="Converts a project from using VST2 plugins to using VST3 plugins (where available).")
    plugins_parser.add_argument(
        "-p", "--projfile", type=file_type, required=True, help="The project file to convert.")
    plugins_parser.add_argument(
        "-y", "--includeplugs", type=regex_type, help="Regex for the plugins to include in the conversion."
    )
    plugins_parser.add_argument(
        "-n", "--ignoreplugs", type=regex_type, help="Regex for the plugins to include in the conversion."
    )
    plugins_parser.add_argument(
        "-w", "--ignorewarnings", action="store_true", help="Ignores version warnings."
    )
    plugins_parser.set_defaults(func=plugins.handle_command)

    try:
        args = parser.parse_args(argv)
    except ArgumentTypeError as e:
        print(e)
        return

    args.func(args)
