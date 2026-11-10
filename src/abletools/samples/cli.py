import logging
import os
import sys


from argparse import ArgumentParser, BooleanOptionalAction, Namespace
from typing import List, Optional


from abletools.samples.formatter import FolderFormatter, UsageFormatter
from abletools.samples.projects import Project, find_project_files, read_projects
from abletools.samples.scanner import Scanner, ScanResult, find_unused_folders
from abletools.utils import tree_browser
from abletools.utils.cli_utils import Subparsers, add_command, dir_type, path_type
from abletools.utils.process_utils import is_process_running
from abletools.utils.tree import print_tree
from abletools.utils.tui_utils import Style, clear_line, format_path, format_size, pluralize, print_progress_bar, print_status, stylize, supports_color


def add_commands(subparsers: Subparsers):
    unused_parser = add_command(
        subparsers, "unused-samples", find_unused_samples,
        help="Find sample folders that none of your projects use.",
        description="Finds sample folders that none of your projects use, and shows why the other folders are used.",
        examples=["abletools unused-samples ~/Music/Projects ~/Music/Samples",
                  "abletools unused-samples ~/Music/Projects ~/Music/Samples --all",
                  "abletools unused-samples ~/Music/Projects ~/Music/Samples --interactive"])
    unused_parser.add_argument(
        "projdir", type=dir_type, help="The directory containing your Ableton project folder(s).")
    unused_parser.add_argument(
        "sampledir", type=dir_type, help="The directory containing your sample pack(s).")
    unused_parser.add_argument(
        "-a", "--all", action="store_true", help="Also show the folders that are used, not just the unused ones.")
    _add_scan_arguments(unused_parser)

    usage_parser = add_command(
        subparsers, "sample-usage", show_sample_usage,
        help="Show which samples are used in which projects.",
        examples=["abletools sample-usage ~/Music/Projects",
                  "abletools sample-usage ~/Music/Projects ~/Music/Samples --by-sample",
                  "abletools sample-usage \"My Song Project/My Song.als\""])
    usage_parser.add_argument(
        "projpath", type=path_type, help="A project file, or the directory containing your Ableton project folder(s).")
    usage_parser.add_argument(
        "sampledir", type=dir_type, nargs="?", help="Only show the samples inside this directory.")
    usage_parser.add_argument(
        "-s", "--by-sample", action="store_true", help="List the projects that use each sample, instead of the samples that each project uses.")
    _add_scan_arguments(usage_parser)


def find_unused_samples(args: Namespace):
    if is_process_running("Live"):
        print("Please close Ableton Live before running this command.")
        return

    projects = _read_projects(args.projdir, args)
    if projects is None:
        return

    _print_status("Scanning samples...")
    scanner = Scanner()
    scanner.scan(projects, args.sampledir, args.recursive)
    _clear_status()

    root = FolderFormatter(scanner.result, args.projdir).build()
    if _should_browse(args):
        tree_browser.browse_tree(root, f"Sample folders in {format_path(scanner.result.root.path)}",
                                 filter_name="unused only", flagged_only=not args.all)
        return

    print_tree(root, flagged_only=not args.all)
    _print_unused_summary(scanner.result, args)


def show_sample_usage(args: Namespace):
    if is_process_running("Live"):
        logging.warning(
            "Ableton Live is running, so changes that have not been saved will not be shown.")

    projects = _read_projects(args.projpath, args)
    if projects is None:
        return

    formatter = UsageFormatter(projects, args.projpath, args.sampledir)
    browse = _should_browse(args)
    # the browser starts with everything collapsed, so that it is easier to find your way around
    if args.by_sample:
        root = formatter.build_by_sample(expanded=not browse)
    else:
        root = formatter.build_by_project(expanded=not browse)

    if browse:
        tree_browser.browse_tree(root, "Samples by project" if not args.by_sample else
                                 "Projects by sample")
        return

    print_tree(root)
    # tips are only useful to people, not to scripts reading the output
    if not sys.stdout.isatty():
        return
    tip = "Use --by-sample to list the projects that use each sample" if not args.by_sample else \
        "Leave out --by-sample to list the samples that each project uses"
    print(stylize(f"\n{tip}, or --interactive to browse.",
          Style.DIM, supports_color()))


def _add_scan_arguments(parser: ArgumentParser):
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="Browse the results in an interactive tree view.")
    parser.add_argument("--include-backups", action="store_true",
                        help="Also scan the project files in backup folders.")
    parser.add_argument(
        "--recursive", action=BooleanOptionalAction, default=True, help="Scan subdirectories for project files and samples (on by default).")


def _read_projects(project_path: str, args: Namespace) -> Optional[List[Project]]:
    """Reads the projects to scan, printing a message and returning None if there are none."""
    project_files = find_project_files(
        project_path, args.recursive, args.include_backups)
    if len(project_files) == 0:
        print(f"No project files (.als) found in '{project_path}'.")
        return None

    projects = read_projects(project_files, _print_progress)
    _clear_status()

    for project in projects:
        if project.error is not None:
            logging.warning(
                f"Could not read project file '{project.path}', so its samples are not included. Error: {project.error}")
    return projects


def _should_browse(args: Namespace) -> bool:
    if not args.interactive:
        return False
    if not tree_browser.can_browse():
        if not tree_browser.HAS_CURSES:
            logging.warning(
                "Interactive mode needs the curses module, which can be installed with 'pip install windows-curses'.")
        else:
            logging.warning("Interactive mode only works in a terminal.")
        return False
    return True


def _print_unused_summary(result: ScanResult, args: Namespace):
    color = supports_color()
    unused = find_unused_folders(result.root)
    print()
    if len(unused) == 0:
        print("No unused folders. Every folder contains samples that are used by at least one project.")
    else:
        sample_count = sum(node.sample_count for node in unused)
        size = sum(node.size for node in unused)
        print(stylize(f"{pluralize(len(unused), 'unused folder')} · {pluralize(sample_count, 'sample')} · {format_size(size)}",
                      Style.YELLOW, color))

    backups = " (including backups)" if args.include_backups else ""
    unreadable = len([project for project in result.projects
                      if project.error is not None])
    skipped = f", {unreadable:,} of which could not be read" if unreadable > 0 else ""
    print(f"Scanned {pluralize(len(result.projects), 'project')}{backups} in "
          f"{format_path(os.path.abspath(args.projdir))}{skipped}.")
    if sys.stdout.isatty() and not args.all:
        print(stylize(
            "Use --all to also show the folders that are used, or --interactive to browse.", Style.DIM, color))


def _print_progress(project_index: int, project_count: int):
    if sys.stderr.isatty():
        print_progress_bar(project_index, project_count, prefix="Reading projects",
                           suffix=f"({project_index}/{project_count})", length=32)


def _print_status(message: str):
    if sys.stderr.isatty():
        print_status(message)


def _clear_status():
    if sys.stderr.isatty():
        clear_line()
