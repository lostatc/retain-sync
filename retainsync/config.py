"""Hold global variables accessible from all modules."""

from collections import defaultdict

# Hold the parsed command-line arguments.
cmd_args = defaultdict(lambda: None)

# Hold a ProfileDir object for the specified profile.
main = None

# Hold ProfileDir objects for each profile.
profiles = {}

# Hold an SSHConnection object for the session.
ssh = None
