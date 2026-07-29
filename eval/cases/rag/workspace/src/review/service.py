class ReviewFinding:
    """A finding points back to an exact changed diff location."""

    file_path: str
    line_start: int
    line_end: int | None
    side: str  # HEAD identifies a line added or modified by the proposed change.
