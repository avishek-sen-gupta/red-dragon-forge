import logging

from cobble.elapsed_formatter import ElapsedFormatter


def _formatted(seconds: float, message: str) -> str:
    record = logging.LogRecord("cobble", logging.INFO, __file__, 1, message, (), None)
    record.relativeCreated = seconds * 1000
    return ElapsedFormatter().format(record)


def test_every_line_says_how_long_the_run_has_taken() -> None:
    assert [
        _formatted(0.4, "loading"),
        _formatted(75.9, "round 1"),
        _formatted(3723.2, "round 8"),
        _formatted(90061.0, "still going"),
    ] == [
        "[0h00m00s] loading",
        "[0h01m15s] round 1",
        "[1h02m03s] round 8",
        "[25h01m01s] still going",
    ]
