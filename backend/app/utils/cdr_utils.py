import re


def duration_to_seconds(duration: str) -> int:
    """
    Convert a duration such as
    '01h 23m 45s'
    into total seconds.
    """

    pattern = r"(\d+)h\s*(\d+)m\s*(\d+)s"

    match = re.match(pattern, duration.strip())

    if not match:
        raise ValueError(
            f"Invalid duration format: {duration}"
        )

    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = int(match.group(3))

    return (
        hours * 3600
        + minutes * 60
        + seconds
    )