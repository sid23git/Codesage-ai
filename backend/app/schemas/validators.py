"""Small, shared Pydantic validation helpers used across M6 request schemas.

Kept separate from any single schema module because the same rule
(``end_line`` must not precede ``start_line``) is enforced identically by
more than one request schema (``ExplainRequest``, ``ReviewRequest``) — this
avoids two copies of the same check silently drifting apart.
"""

from __future__ import annotations


def validate_line_range(start_line: int | None, end_line: int | None) -> None:
    """Raise ``ValueError`` if *end_line* precedes *start_line*.

    A no-op when either bound is omitted -- an open-ended range on either
    side is valid; only an inverted, fully-specified range is rejected.
    """
    if start_line is not None and end_line is not None and end_line < start_line:
        raise ValueError("end_line must be greater than or equal to start_line.")
