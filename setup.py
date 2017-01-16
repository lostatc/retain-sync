from setuptools import setup

setup(
    name="retain-sync",
    version="0.1",
    description="Distribute files based on how frequently they are accessed.",
    url="https://github.com/lostatc/retain-sync",
    author="Garrett Powell",
    author_email="garrett@gpowell.net",
    license="GPLv3",
    data_files=[
        ("bin",
            ["scripts/retain-sync"]),
        ("share/man/man1",
            ["docs/retain-sync.1"]),
        ("share/retain-sync",
            ["docs/templates/config-template"]),
        ("share/licenses/retain-sync",
            ["LICENSE"]),
        ("lib/systemd/user",
            ["docs/unit/retain-sync@.service"])
        ],
    packages=[
        "retainsync", "retainsync.io", "retainsync.util",
        "retainsync.commands"
        ]
    )
