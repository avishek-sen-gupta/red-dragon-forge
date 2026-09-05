"""The one place a corpus is turned into ASGs, and the one place they are read back.

Parsing a corpus is 4-7 seconds of JVM per program, so no stage after this one
should ever do it: the knowledge graph, the dependency graph and the source CFGs
all read the cache this package writes. Keeping the parse in its own package is
what makes that literal -- there is exactly one writer and one naming rule, and a
stage that wants an ASG asks asg_cache for it rather than starting a JVM.
"""
