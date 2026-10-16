"""A build that names a coprocessor but does not link one of the programs it requires."""


class MissingRequiredProgram(ValueError):
    pass
