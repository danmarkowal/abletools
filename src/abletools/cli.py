import abletools.plugins.cli as plugins
import abletools.projects.cli as projects
import abletools.samples.cli as samples


from argparse import ArgumentParser, ArgumentTypeError
from typing import Optional, Sequence


from abletools.plugins.cli import ConversionMode
from abletools.utils.cli_utils import dir_type, file_type, regex_type


def main(argv: Optional[Sequence[str]] = None):
    parser = ArgumentParser(
        prog="abletools",
        description="CLI tools for Ableton Live.")
    subparsers = parser.add_subparsers(dest="commands", required=True)

    samples_parser = subparsers.add_parser(
        "unused-samples", description="Finds unused samplepacks.")
    samples_parser.add_argument(
        "projdir", type=dir_type, help="The directory containing your Ableton project folder(s).")
    samples_parser.add_argument(
        "sampledir", type=dir_type, help="The directory containing your sample pack(s).")
    samples_parser.add_argument(
        "-r", "--recursive", action="store_false", help="Scan for project files recursively.")
    samples_parser.add_argument(
        "--debug", action="store_true", help="Print debug information.")
    samples_parser.add_argument("--include-backups", action="store_true",
                                help="Scan for samples in backup project folder.")
    samples_parser.set_defaults(func=samples.find_unused_samples)

    plugins_parser = subparsers.add_parser(
        "convert", description="Converts a project from using VST2 plugins to using VST3 plugins (where available).")
    plugins_parser.add_argument(
        "projfile", type=file_type, help="The project file to convert.")
    plugins_parser.add_argument(
        "-y", "--includeplugs", type=regex_type, help="Regex for the plugins to include in the conversion."
    )
    plugins_parser.add_argument(
        "-n", "--ignoreplugs", type=regex_type, help="Regex for the plugins to include in the conversion."
    )
    plugins_parser.add_argument(
        "-p", "--patchdir", type=dir_type, help="The path to any additional patches used to convert plugin data for plugins with different representations for VST2 and VST3."
    )
    plugins_parser.add_argument(
        "--nodefaultpatches", action="store_true", help="Disable the built-in default patches and only use custom patches provided via --patchdir."
    )
    plugins_parser.add_argument(
        "-m", "--mode", type=ConversionMode, choices=list(ConversionMode), default=ConversionMode.NECESSARY, help="The conversion mode to use. The 'necessary' mode only converts a VST2 plugin if it is not found in the Live database, while the 'all' mode converts all VST2 plugins regardless of whether they are found in the Live database or not.")
    plugins_parser.set_defaults(func=plugins.convert_vst2_to_vst3)

    unpack_parser = subparsers.add_parser(
        "unpack", description="Converts an Ableton project file to a readable XML file.")
    unpack_parser.add_argument(
        "projfile", type=file_type, help="The project file to unpack.")
    unpack_parser.set_defaults(func=projects.unpack_project)

    pack_parser = subparsers.add_parser(
        "pack", description="Converts an XML file to an Ableton project file.")
    pack_parser.add_argument("projfile", type=file_type,
                             help="The project file to pack.")
    pack_parser.set_defaults(func=projects.pack_project)

    try:
        args = parser.parse_args(argv)
    except ArgumentTypeError as e:
        print(e)
        return

    args.func(args)
