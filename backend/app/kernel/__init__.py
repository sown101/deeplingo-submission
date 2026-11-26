"""Shared kernel: the few values every learning-loop module shares.

Admission rule: an enum or identifier used at runtime by three or more modules
whose owning module sits above some of its consumers in the module DAG. Nothing
else belongs here; this is not a place for shared models or helpers.
"""
