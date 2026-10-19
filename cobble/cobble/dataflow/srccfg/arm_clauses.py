"""The phrases lowered as a two-armed decision after their statement.

Each is (the phrase's attribute, its NOT form's attribute, the label its test
reads). desugar lowers them; the statement index walks the same attributes, so
both read this one list.
"""

ARM_CLAUSES = (
    ("at_end", "not_at_end", "AT END"),
    ("invalid_key", "not_invalid_key", "INVALID KEY"),
    ("on_size_error", "not_on_size_error", "ON SIZE ERROR"),
    ("on_exception", "not_on_exception", "ON EXCEPTION"),
    ("on_overflow", "not_on_overflow", "ON OVERFLOW"),
    ("at_end_of_page", "not_at_end_of_page", "END-OF-PAGE"),
)
