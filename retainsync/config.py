"""Hold global variables accessible from all modules."""

from collections import defaultdict

# Hold all the parsed command-line arguments.
cmd_args = defaultdict(lambda: None)

# Hold the name of the specified profile.
name = ""

# Hold ProfileDir objects for each profile.
profiles = {}

# Hold a ProfileDir object for the specified profile.
main = None
