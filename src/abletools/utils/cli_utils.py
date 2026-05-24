LINE_CLEAR = '\x1b[2K'


# https://stackoverflow.com/questions/3173320/text-progress-bar-in-terminal-with-block-characters
def print_progress_bar(iteration: int, total: int, prefix: str = "", suffix: str = "", decimals: int = 1, length: int = 100, fill: str = "█", end: str = "\r"):
    percent = ("{0:." + str(decimals) + "f}").format(100 *
                                                     (iteration / float(total)))
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + "-" * (length - filled_length)
    print(f'\r{prefix} |{bar}| {percent}% {suffix}', end=end)


def clear_line():
    print(end=LINE_CLEAR)
