from setuptools import setup

setup(
    name="zielen",
    version="0.1",
    description="Distribute files based on how frequently they are accessed.",
    url="https://github.com/lostatc/zielen",
    author="Garrett Powell",
    author_email="garrett@gpowell.net",
    license="GPLv3",
    install_requires=["Sphinx", "pyinotify", "linotype"],
    python_requires=">=3.5",
    tests_require=["pytest", "pyfakefs"],
    packages=["zielen", "zielen.commands"])
