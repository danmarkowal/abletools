import logging
import sys

import abletools.plugins.cli as plugins
import abletools.projects.cli as projects
import abletools.samples.cli as samples


from argparse import ArgumentParser
from typing import Optional, Sequence


def main(argv: Optional[Sequence[str]] = None):
    parser = ArgumentParser(
        prog="abletools",
        description="CLI tools for Ableton Live.",
        epilog="Run 'abletools <command> --help' to see the options and examples for a command.")
    subparsers = parser.add_subparsers(
        title="commands", dest="command", metavar="<command>")

    # each package defines its own commands
    samples.add_commands(subparsers)
    plugins.add_commands(subparsers)
    projects.add_commands(subparsers)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return

    if args.debug:
        logging.basicConfig(level=logging.DEBUG,
                            format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler()])
    else:
        logging.basicConfig(level=logging.INFO,
                            format="[%(levelname)s] %(message)s", handlers=[logging.StreamHandler()])

    try:
        args.func(args)
    except KeyboardInterrupt:
        # exit quietly when Ctrl+C is pressed
        print()
        sys.exit(130)
