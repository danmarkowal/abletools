from argparse import Namespace


from abletools.utils.cli_utils import print_progress_bar, clear_line
from abletools.utils.process_utils import is_process_running
from abletools.samples.formatter import Formatter
from abletools.samples.scanner import Scanner


def handle_command(args: Namespace):
    if is_process_running("Live"):
        print("Please close Ableton Live before running this command.")
        return

    scanner = Scanner(lambda project_index, project_count: print_progress_bar(
        project_index, project_count, prefix="Progress", length=32))
    scanner.scan(args.projdir, args.sampledir,
                 args.recursive, args.include_backups)
    clear_line()

    formatter = Formatter()
    formatter.print_unused(scanner.result.root)
