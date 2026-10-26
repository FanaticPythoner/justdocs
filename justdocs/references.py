"""Define Markdown reference declarations shared by content processors."""

import re

HEADING_PATTERN = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$", re.MULTILINE)
REFERENCE_ID_PATTERN = re.compile(r"[A-Z][A-Z0-9]*\d+(?:-\d+)*", re.IGNORECASE)
REFERENCE_HEADING_PATTERN = re.compile(
    r"^\[(?P<id>[A-Z][A-Z0-9]*\d+(?:-\d+)*)\]\s+(?P<title>.+)$",
    re.IGNORECASE,
)
FENCE_PATTERN = re.compile(
    r"(?ms)^[ \t]{0,3}(?P<backticks>`{3,})[^`\n]*(?:\n|\Z)"
    r".*?(?:^[ \t]{0,3}(?P=backticks)`*[ \t]*(?:\n|\Z)|\Z)"
    r"|^[ \t]{0,3}(?P<tildes>~{3,})[^\n]*(?:\n|\Z)"
    r".*?(?:^[ \t]{0,3}(?P=tildes)~*[ \t]*(?:\n|\Z)|\Z)",
)
