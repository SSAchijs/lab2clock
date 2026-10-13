"""Load API keys and other settings from a local .env file."""

from dotenv import find_dotenv, load_dotenv


def load_env() -> bool:
    """Load .env (searched upward from the working directory) into the environment.

    Variables already set in the environment are not overridden.
    Returns True if a .env file was found.
    """
    # Without usecwd, python-dotenv searches from this file's folder,
    # not from where you run the program.
    return load_dotenv(find_dotenv(usecwd=True), override=False)
