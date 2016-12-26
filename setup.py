from setuptools import setup

setup(
    name="retain-sync",
    version="0.1",
    description="Distribute files based on how frequently they are accessed.",
    url="https://github.com/lostatc/retain-sync",
    author="Garrett Powell",
    author_email="garrett@gpowell.net",
    license="GPLv3",
    packages=[
        "retainsync", "retainsync.io", "retainsync.util",
        "retainsync.commands"
        ]
    )
