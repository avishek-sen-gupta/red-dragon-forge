"""The smallest corpus TOML the combine commands accept, with the ASG cache left to fill in."""

CONFIG = """\
[corpus]
cobol_dir = "."
cobol_globs = ["*.cbl"]
jcl_dir = "."
jcl_globs = ["*.jcl"]
copybook_dirs = ["."]
asg_dir = "{asg}"
"""
