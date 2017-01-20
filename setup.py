from setuptools import setup

setup(
    name="zielen",
    version="0.1",
    description="Distribute files based on how frequently they are accessed.",
    url="https://github.com/lostatc/zielen",
    author="Garrett Powell",
    author_email="garrett@gpowell.net",
    license="GPLv3",
    data_files=[
        ("bin",
            ["scripts/zielen"]),
        ("share/man/man1",
            ["docs/zielen.1"]),
        ("share/zielen",
            ["docs/templates/config-template"]),
        ("share/licenses/zielen",
            ["LICENSE"]),
        ("lib/systemd/user",
            ["docs/unit/zielen@.service"])
        ],
    packages=[
        "zielen", "zielen.io", "zielen.util", "zielen.commands"
        ]
    )
