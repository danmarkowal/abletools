import os
import signal
import subprocess
import sys

import psutil


from multiprocessing import Pool
from typing import Callable, Collection, List, Optional


if sys.platform == "darwin":
    FILE_MANAGER_NAME = "Finder"
elif sys.platform == "win32":
    FILE_MANAGER_NAME = "Explorer"
else:
    FILE_MANAGER_NAME = "file manager"


def is_process_running(process_name: str):
    for process in psutil.process_iter():
        try:
            if process_name.lower() == process.name().lower():
                return process.is_running()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False


def reveal_in_file_manager(path: str):
    """Opens the folder containing a file or folder, with the file or folder selected (where supported)."""
    if sys.platform == "darwin":
        command = ["open", "-R", path]
    elif sys.platform == "win32":
        command = ["explorer", f"/select,{path}"]
    else:
        command = ["xdg-open", os.path.dirname(path)]
    subprocess.run(command, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def map_in_processes[T, R](func: Callable[[T], R], items: Collection[T], on_process: Optional[Callable[[int, int], None]] = None) -> List[R]:
    """Calls a function on each item using all CPU cores. The results are in the order they finished in.

    :param func: A top-level function (so that it can be sent to other processes) that does not raise.
    :param on_process: Called after each item with (item_index, item_count).
    """
    results: List[R] = []
    hardware_concurrency = os.cpu_count()
    with Pool(processes=hardware_concurrency, initializer=_ignore_interrupts) as p:
        for result in p.imap_unordered(func, items):
            results.append(result)
            # callback for progress bar
            if on_process is not None:
                on_process(len(results), len(items))
    return results


def _ignore_interrupts():
    # only the main process should handle Ctrl+C, otherwise every worker prints a traceback
    signal.signal(signal.SIGINT, signal.SIG_IGN)
