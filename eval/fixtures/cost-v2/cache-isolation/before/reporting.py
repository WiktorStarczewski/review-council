"""Render already formatted labels and values as plain text, without I/O."""


def render_rows(rows: list[tuple[str, str]]) -> str:
    return "\n".join(f"{label}: {value}" for label, value in rows)
