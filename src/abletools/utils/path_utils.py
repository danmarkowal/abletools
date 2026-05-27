from pathlib import Path


from platformdirs import user_cache_path


def get_cache_path() -> Path:
    return user_cache_path("abletools", "danmarkowal")
