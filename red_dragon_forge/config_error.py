"""A build.toml or env.toml that does not describe a build or a run, named by its file."""


class ConfigError(ValueError):
    pass
