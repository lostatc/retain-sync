import os

XDG_CONFIG_HOME = os.getenv(
    "XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
XDG_DATA_HOME = os.getenv(
    "XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
XDG_RUNTIME_DIR = os.getenv(
    "XDG_RUNTIME_DIR", os.path.join("/run/user", str(os.getuid())))

PROGRAM_DIR = os.path.join(XDG_CONFIG_HOME, "zielen")
PROFILES_DIR = os.path.join(PROGRAM_DIR, "profiles")
