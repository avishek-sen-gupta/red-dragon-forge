"""cobble.diagnosis — read-only reports on what a corpus build will fail on.

Every module here answers one question about a corpus *before* the expensive
phase that would otherwise answer it slowly: which COPY statements will not
resolve, which JCL members will not parse. A corpus build takes hours and one
JVM subprocess per member; a diagnosis takes minutes and tells you what to fix
first.

They share a shape, and new ones should keep it:

  - ``--config`` names a corpus YAML, so a diagnosis runs against exactly the
    directories and globs the build will use;
  - stdout (or ``--output``) is JSON and nothing else, because the names in it
    are the corpus's own identifiers and the caller chooses where they land;
  - the human summary is LOGGED, so it goes to stderr and carries shape only --
    counts, concentration, which fix applies -- never a corpus name;
  - the exit status is 0 whatever is found. These report; they do not gate.
"""
