"""Modify formatting of an html man page."""

import re
import sys
import os

from bs4 import BeautifulSoup

in_file = sys.argv[1]
if not os.path.isfile(in_file):
    raise OSError("argument must be a file")

with open(in_file) as man_file:
    soup = BeautifulSoup(man_file, "lxml")

# Link external CSS stylesheet.
soup.head.append(soup.new_tag(
    "link", rel="stylesheet", type="text/css", href="man.css"))

# Wrap heading hyperlinks with a CSS class.
first_link = soup.find("a", href=re.compile("^#"))
nav_tag = soup.new_tag("div")
nav_tag["class"] = "man-navigation"
first_link.insert_before(nav_tag)
for link in [first_link] + first_link.find_next_siblings(["a", "br"]):
    link.extract()
    nav_tag.append(link)

with open(in_file, "w") as man_file:
    man_file.write(soup.prettify())
