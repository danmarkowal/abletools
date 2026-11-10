import logging
import os
import sys


from argparse import Namespace
from functools import partial
from pathlib import Path
from typing import List, Optional, Tuple


from abletools.api.patch import PluginPatch
from abletools.plugins.browser import ConversionBrowser
from abletools.plugins.conversion import ConversionMode, ConversionOptions, PluginStatus, convert_project, plan_project_file
from abletools.plugins.formatter import InventoryFormatter
from abletools.plugins.inventory import has_audio_units, read_project_plugins, take_inventory
from abletools.plugins.live_db import LivePluginDB
from abletools.plugins.patch_registry import PatchError, PatchRegistry
from abletools.plugins.plugin_db import PluginDBError
from abletools.samples.projects import find_project_files
from abletools.utils import tree_browser
from abletools.utils.cli_utils import Subparsers, add_command, dir_type, path_type, regex_type
from abletools.utils.process_utils import is_process_running, map_in_processes
from abletools.utils.tree import print_tree
from abletools.utils.tui_utils import Style, clear_line, format_path, print_progress_bar, stylize, supports_color


def add_commands(subparsers: Subparsers):
    parser = add_command(
        subparsers, "convert", convert_vst2_to_vst3,
        help="Convert the VST2 plugins in a project to VST3 plugins.",
        description="Converts a project from using VST2 plugins to using VST3 plugins (where available). "
                    "The converted project is saved next to the original as '<name> (Converted <date>).als'. "
                    "Use --interactive to browse a folder of projects, see which ones were converted already "
                    "and choose which patches to use.",
        examples=["abletools convert \"My Song.als\"",
                  "abletools convert \"My Song.als\" --mode all --ignore-plugins \"^Serum$\"",
                  "abletools convert ~/Music/Projects --interactive --patch-dir ~/my-patches"])
    parser.add_argument(
        "projpath", type=path_type, help="The project file to convert, or a directory containing your Ableton project folder(s) to see what converting them would do.")
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="Browse the projects and patches in an interactive tree view and choose what to convert.")
    parser.add_argument(
        "-y", "--include-plugins", type=regex_type, metavar="REGEX", help="Regex for the plugins to include in the conversion."
    )
    parser.add_argument(
        "-n", "--ignore-plugins", type=regex_type, metavar="REGEX", help="Regex for the plugins to exclude from the conversion."
    )
    parser.add_argument(
        "-p", "--patch-dir", type=dir_type, metavar="DIR", help="The path to any additional patches used to convert plugin data for plugins with different representations for VST2 and VST3."
    )
    parser.add_argument(
        "--no-default-patches", action="store_true", help="Disable the built-in default patches and only use custom patches provided via --patch-dir. With --interactive, the built-in patches start off unticked instead."
    )
    parser.add_argument(
        "--include-backups", action="store_true", help="When given a directory, also include the project files in backup folders.")
    parser.add_argument(
        "-m", "--mode", type=ConversionMode, choices=list(ConversionMode), default=ConversionMode.NECESSARY, help="The conversion mode to use. The 'necessary' mode only converts a VST2 plugin if it is not found in the Live database, while the 'all' mode converts all VST2 plugins regardless of whether they are found in the Live database or not (installed VST2 plugins without a VST3 version are kept).")

    usage_parser = add_command(
        subparsers, "plugin-usage", show_plugin_usage,
        help="List the plugins your projects use, and which ones to install to convert them.",
        description="Lists every plugin used in your projects with its formats (VST2, VST3, AU) and whether each format "
                    "is installed. Plugins whose VST3 versions you need to install to convert your projects come first, "
                    "in the order that lets the most projects be fully converted.",
        examples=["abletools plugin-usage ~/Music/Projects",
                  "abletools plugin-usage ~/Music/Projects --interactive"])
    usage_parser.add_argument(
        "projpath", type=path_type, help="A project file, or the directory containing your Ableton project folder(s).")
    usage_parser.add_argument(
        "-i", "--interactive", action="store_true", help="Browse the plugins in an interactive tree view, including which projects use each one.")
    usage_parser.add_argument(
        "--include-backups", action="store_true", help="Also scan the project files in backup folders.")


def convert_vst2_to_vst3(args: Namespace):
    if is_process_running("Live"):
        logging.error("Please close Ableton Live before running this command.")
        return

    patches = _load_patches(args)
    if patches is None:
        return

    try:
        db = LivePluginDB()
        db.open_connection()
    except PluginDBError as e:
        logging.error(f"Error initialising Live plugin database. Error {e}")
        return

    options = ConversionOptions(
        args.mode, args.include_plugins, args.ignore_plugins)
    try:
        if args.interactive or os.path.isdir(args.projpath):
            _browse_projects(args, patches, db, options)
        else:
            _convert_project_file(args, patches, db, options)
    finally:
        db.close_connection()


def _convert_project_file(args: Namespace, patches: List[Tuple[PluginPatch, str, bool]], db: LivePluginDB, options: ConversionOptions):
    registry = PatchRegistry(
        [patch for patch, _, enabled in patches if enabled])
    result = convert_project(Path(args.projpath), db, registry, options)

    installed = len([plan for plan in result.plans
                     if plan.get_status(options.mode) == PluginStatus.INSTALLED])
    if installed > 0:
        logging.info(
            f"Left {installed} installed VST2 plugins alone. Use '--mode all' to convert them too.")
    if len(result.kept) > 0:
        logging.info(
            f"Kept {len(result.kept)} installed VST2 plugins that could not be converted to VST3.")


def _browse_projects(args: Namespace, patches: List[Tuple[PluginPatch, str, bool]], db: LivePluginDB, options: ConversionOptions):
    """Shows what converting each project would do, in the tree browser if --interactive was given."""
    browse = args.interactive and tree_browser.can_browse()
    if args.interactive and not browse:
        logging.warning(
            "Interactive mode needs a terminal and the curses module (on Windows: 'pip install windows-curses').")

    project_files = find_project_files(
        args.projpath, True, args.include_backups)
    if len(project_files) == 0:
        print(f"No project files (.als) found in '{args.projpath}'.")
        return

    # planning needs the conversion options, so they are passed along to the worker processes
    plans = map_in_processes(
        partial(plan_project_file, options=options), project_files, _print_progress)
    if sys.stderr.isatty():
        clear_line()

    browser = ConversionBrowser(args.projpath, plans, patches, db, options)
    root = browser.build()
    if browse:
        tree_browser.browse_tree(root, f"Convert VST2 plugins to VST3 in {format_path(os.path.abspath(args.projpath))}",
                                 filter_name="to convert only", actions=browser.get_actions(),
                                 on_check=lambda item: browser.refresh())
        return

    print_tree(root)
    if sys.stdout.isatty():
        print(stylize("\nRun this again with --interactive to see each project's plugins and convert them.",
                      Style.DIM, supports_color()))


def show_plugin_usage(args: Namespace):
    if is_process_running("Live"):
        logging.warning(
            "Ableton Live is running, so changes that have not been saved will not be shown.")

    try:
        audio_units = has_audio_units()
    except PluginDBError as e:
        logging.error(f"Error initialising Live plugin database. Error {e}")
        return

    project_files = find_project_files(
        args.projpath, True, args.include_backups)
    if len(project_files) == 0:
        print(f"No project files (.als) found in '{args.projpath}'.")
        return

    projects = map_in_processes(
        read_project_plugins, project_files, _print_progress)
    if sys.stderr.isatty():
        clear_line()
    for project in projects:
        if project.error is not None:
            logging.warning(
                f"Could not read project file '{project.path}', so its plugins are not included. Error: {project.error}")

    root = InventoryFormatter(take_inventory(
        projects, audio_units), args.projpath).build()
    if args.interactive and tree_browser.can_browse():
        tree_browser.browse_tree(root, f"Plugins used in {format_path(os.path.abspath(args.projpath))}",
                                 filter_name="to install only")
        return
    if args.interactive:
        logging.warning(
            "Interactive mode needs a terminal and the curses module (on Windows: 'pip install windows-curses').")

    print_tree(root)
    if sys.stdout.isatty():
        print(stylize("\nUse --interactive to see which projects use each plugin.",
                      Style.DIM, supports_color()))


def _load_patches(args: Namespace) -> Optional[List[Tuple[PluginPatch, str, bool]]]:
    """Returns each patch, where it comes from and whether it should be used.

    Outside of interactive mode, disabled patches are left out of the conversion.
    """
    default_patches = PatchRegistry()
    default_patches.load_default_patches()
    patches = [(patch, "built-in", not args.no_default_patches)
               for patch in default_patches.get_patches()]

    if args.patch_dir:
        user_patches = PatchRegistry()
        try:
            user_patches.load_user_patches(Path(args.patch_dir))
        except PatchError as e:
            logging.error(e)
            return None
        patches += [(patch, format_path(os.path.abspath(args.patch_dir)), True)
                    for patch in user_patches.get_patches()]
        logging.info(
            f"Loaded {user_patches.get_patch_count()} user patches from directory: '{args.patch_dir}'.")
    return patches


def _print_progress(project_index: int, project_count: int):
    if sys.stderr.isatty():
        print_progress_bar(project_index, project_count, prefix="Reading projects",
                           suffix=f"({project_index}/{project_count})", length=32)
