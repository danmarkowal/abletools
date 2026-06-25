import os
import re


from argparse import ArgumentTypeError


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
