import os
import re
import shutil
import textwrap


from argparse import ArgumentParser, ArgumentTypeError, Namespace, RawDescriptionHelpFormatter, _SubParsersAction
from typing import Callable, Optional, Sequence


type Subparsers = _SubParsersAction[ArgumentParser]


def add_command(subparsers: Subparsers, name: str, func: Callable[[Namespace], None], help: str, description: Optional[str] = None, examples: Sequence[str] = ()) -> ArgumentParser:
    """Adds a command with the options that all commands share.

    :param subparsers: The subparsers of the main parser.
    :param name: The name used to run the command, e.g. 'unused-samples'.
    :param func: The function that runs the command.
    :param help: A one-line summary shown in the list of commands.
    :param description: A longer description shown in the help of the command. Defaults to the summary.
    :param examples: Example usages shown at the bottom of the help of the command.
    """
    epilog = None
    if len(examples) > 0:
        epilog = "examples:\n" + \
            "\n".join(f"  {example}" for example in examples)

    # the raw formatter keeps the line breaks between the examples, so the description has to be wrapped here
    # (argparse leaves a margin of two columns too)
    width = shutil.get_terminal_size().columns - 2
    description = textwrap.fill(description or help, width)

    parser = subparsers.add_parser(
        name, help=help, description=description, epilog=epilog, formatter_class=RawDescriptionHelpFormatter)
    parser.add_argument(
        "--debug", action="store_true", help="Print debug information.")
    parser.set_defaults(func=func)
    return parser


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


def path_type(arg: str) -> str:
    if os.path.exists(arg):
        return arg
    else:
        raise ArgumentTypeError(f"File or directory not found: '{arg}'.")


def regex_type(arg: str) -> re.Pattern[str]:
    try:
        return re.compile(arg)
    except re.error as e:
        raise ArgumentTypeError(
            f"Invalid regex pattern: '{arg}'. Error: {e}")
