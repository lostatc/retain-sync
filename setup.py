from setuptools import setup

setup(
    name="zielen",
    version="0.1",
    description="Distribute files based on how frequently they are accessed.",
    url="https://github.com/lostatc/zielen",
    author="Garrett Powell",
    author_email="garrett@gpowell.net",
    license="GPLv3",
    install_requires=["Sphinx", "pyinotify"],
    python_requires=">=3.5",
    tests_require=["pytest", "pyfakefs"],
    data_files=[
        ("bin",
            ["scripts/zielen", "scripts/zielend"]),
        ("share/licenses/zielen",
            ["LICENSE"]),
        ("share/zielen",
            ["docs/templates/config-template"]),
        ("lib/systemd/user",
            ["docs/unit/zielen@.service"]),
        ("share/man/man1",
            ["docs/_build/man/zielen.1"])
        ],
    packages=[
        "zielen", "zielen.commands"
        ]
    )
