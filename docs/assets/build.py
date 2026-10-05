#!/usr/bin/env python3
"""Render the README artwork in a light and a dark variant.

Each figure is one template drawn twice, so both themes always show the same thing.
Run `python3 docs/assets/build.py` after editing a figure and commit the SVGs.
"""

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"

THEMES = {
    "light": {
        "bg0": "#ffffff", "bg1": "#f3f5f8", "card": "#ffffff", "line": "#d1d9e0",
        "text": "#1f2328", "muted": "#59636e", "faint": "#8c959f", "chip": "#eef1f4",
        "sol": "#d97706", "luna": "#7c3aed", "opus": "#dc5a41", "sonnet": "#0f8f84",
        "ok": "#1f883d", "discover": "#0969da", "plan": "#8250df", "fix": "#bc4c00",
        "verify": "#1f883d", "gate": "#57606a",
    },
    "dark": {
        "bg0": "#0d1117", "bg1": "#141a22", "card": "#161b22", "line": "#30363d",
        "text": "#f0f6fc", "muted": "#9198a1", "faint": "#6e7681", "chip": "#21262d",
        "sol": "#f5a524", "luna": "#a78bfa", "opus": "#ff7b63", "sonnet": "#2dd4bf",
        "ok": "#3fb950", "discover": "#4493f8", "plan": "#ab7df8", "fix": "#f0883e",
        "verify": "#3fb950", "gate": "#8b949e",
    },
}

SEATS = ("sol", "luna", "opus", "sonnet")


def svg(width, height, body, title):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="{escape(title)}">\n'
        f"<title>{escape(title)}</title>\n{body}\n</svg>\n"
    )


def text(x, y, s, size, fill, weight=400, family=SANS, anchor="start", extra=""):
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{extra}>{escape(s)}</text>'
    )


def emblem(t, cx, cy, scale=1.0):
    """Four seats around a verdict: the council in one mark."""
    r = 92 * scale
    d = r * 0.7071
    seats = [(cx - d, cy - d), (cx + d, cy - d), (cx + d, cy + d), (cx - d, cy + d)]
    parts = [
        f'<circle cx="{cx}" cy="{cy}" r="{r + 26 * scale:.1f}" fill="none" stroke="{t["line"]}" '
        f'stroke-width="{1.5 * scale:.1f}" stroke-dasharray="{3 * scale:.1f} {7 * scale:.1f}"/>',
        f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" stroke="{t["line"]}" stroke-width="{1.2 * scale:.1f}"/>',
    ]
    for (x, y), seat in zip(seats, SEATS):
        parts.append(
            f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{cx}" y2="{cy}" stroke="{t[seat]}" '
            f'stroke-width="{3 * scale:.1f}" stroke-linecap="round" opacity="0.55"/>'
        )
    for (x, y), seat in zip(seats, SEATS):
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{24 * scale:.1f}" fill="{t[seat]}" opacity="0.18"/>')
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{15 * scale:.1f}" fill="{t[seat]}"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{40 * scale:.1f}" fill="{t["ok"]}"/>')
    s = scale
    parts.append(
        f'<path d="M {cx - 16 * s:.1f} {cy + 1 * s:.1f} L {cx - 4 * s:.1f} {cy + 13 * s:.1f} '
        f'L {cx + 18 * s:.1f} {cy - 12 * s:.1f}" fill="none" stroke="{t["bg0"]}" '
        f'stroke-width="{7 * s:.1f}" stroke-linecap="round" stroke-linejoin="round"/>'
    )
    return "\n".join(parts)


def hero(t):
    w, h = 1200, 340
    body = [
        "<defs>",
        f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{t["bg1"]}"/>'
        f'<stop offset="1" stop-color="{t["bg0"]}"/></linearGradient>',
        f'<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">'
        f'<circle cx="2" cy="2" r="1.2" fill="{t["line"]}"/></pattern>',
        "</defs>",
        f'<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="22" fill="url(#bg)" stroke="{t["line"]}" stroke-width="1.5"/>',
        f'<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="22" fill="url(#dots)" opacity="0.55"/>',
        emblem(t, 205, 170),
        text(380, 148, "review-council", 64, t["text"], 700, MONO, extra=' letter-spacing="-1"'),
        text(382, 198, "A multi-model review council for Claude Code and Codex.", 25, t["text"], 500),
        text(382, 240, "Independent seats from different labs review one change.", 19, t["muted"]),
        text(382, 270, "Every claim is checked against source, fixed, gated and re-verified.", 19, t["muted"]),
    ]
    for i, seat in enumerate(SEATS):
        body.append(f'<rect x="{382 + i * 38}" y="80" width="28" height="6" rx="3" fill="{t[seat]}"/>')
    return svg(w, h, "\n".join(body), "review-council: a multi-model review council for Claude Code and Codex")


def box(x, y, w, h, fill, stroke, rx=12, extra=""):
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="1.5"{extra}/>'
    )


def card(t, key, x, y, w, h, accent):
    """A card whose accent strip follows its rounded top edge."""
    return "\n".join([
        f'<clipPath id="clip-{key}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12"/></clipPath>',
        box(x, y, w, h, t["card"], "none"),
        f'<rect x="{x}" y="{y}" width="{w}" height="5" fill="{t[accent]}" clip-path="url(#clip-{key})"/>',
        box(x, y, w, h, "none", t["line"]),
    ])


def arrow(x1, y1, x2, y2, color, marker="arrow", dashed=False):
    dash = ' stroke-dasharray="5 5"' if dashed else ""
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="2"{dash} '
        f'marker-end="url(#{marker})"/>'
    )


def arrow_marker(color, name="arrow"):
    return (
        f'<marker id="{name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>'
    )


def seat_dots(t, x, y, seats):
    return "\n".join(
        f'<circle cx="{x + i * 15}" cy="{y}" r="5.5" fill="{t[seat]}"/>' for i, seat in enumerate(seats)
    )


# The ordinary loop: (key, title, seats, lines, phase colour).
LOOP = [
    ("discover", "Discover", SEATS, ["every seat looks for", "a smaller change"], "discover"),
    ("triage", "Triage", (), ["open every claim at", "its cited line"], "gate"),
    ("plan", "Plan", ("sol",), ["if the fix is nontrivial,", "one seat checks it"], "plan"),
    ("fix", "Fix + gates", (), ["one commit per fix,", "gates at baseline"], "fix"),
    ("verify", "Verify", SEATS, ["four risk bundles over", "the latest state"], "verify"),
]


def loop(t):
    w, h = 1000, 244
    bw, bh, gap, top = 178, 106, 22, 62
    x0 = (w - (len(LOOP) * bw + (len(LOOP) - 1) * gap)) // 2
    body = [f"<defs>{arrow_marker(t['faint'])}{arrow_marker(t['fix'], 'back')}</defs>"]
    centers = []
    for i, (key, title, seats, lines, phase) in enumerate(LOOP):
        x = x0 + i * (bw + gap)
        centers.append(x + bw / 2)
        body.append(card(t, f"loop-{key}", x, top, bw, bh, phase))
        body.append(text(x + 16, top + 36, title, 18, t["text"], 650))
        for j, line in enumerate(lines):
            body.append(text(x + 16, top + 64 + j * 20, line, 13.5, t["muted"]))
        if seats:
            body.append(seat_dots(t, x + bw - 16 - 15 * (len(seats) - 1), top + 30, seats))
        else:
            body.append(text(x + bw - 16, top + 35, "host", 12, t["faint"], 500, MONO, "end"))
        if i:
            body.append(arrow(x - gap + 4, top + bh / 2, x - 4, top + bh / 2, t["faint"]))
    # Back edge from Verify to Triage: a new P0/P1 or another nontrivial fix reopens the loop.
    yb = top + bh + 34
    body.append(
        f'<path d="M {centers[4]} {top + bh + 4} V {yb} H {centers[1]} V {top + bh + 12}" fill="none" '
        f'stroke="{t["fix"]}" stroke-width="2" stroke-dasharray="6 5" marker-end="url(#back)"/>'
    )
    body.append(text((centers[1] + centers[4]) / 2, yb + 24,
                     "new P0/P1 or another nontrivial fix: plan, fix and verify again", 14, t["fix"], 500,
                     anchor="middle"))
    body.append(text(x0, 36, "preflight: freeze scope, probe every seat", 13.5, t["faint"], 400, MONO))
    body.append(text(w - x0, 36, "clean: seal receipt, report, PR review", 13.5, t["faint"], 400, MONO, "end"))
    return svg(w, h, "\n".join(body), "How one review round runs")


BUNDLES = ("correctness", "security", "concurrency", "regression")
NAMES = {"sol": "Sol", "luna": "Luna", "opus": "Opus", "sonnet": "Sonnet"}

# A large, high-risk review: rows are ("round", label) bands or
# (key, title, note, phase, chips) steps; chips are (seat, label), empty for host work.
LARGE = [
    ("round", "preflight"),
    ("pre", "Freeze and probe", "scope and roster frozen, gates baselined", "gate",
     tuple((s, NAMES[s] + " probe") for s in SEATS)),
    ("round", "discovery"),
    ("r1", "Simplicity", "r1  ·  can the change be smaller?", "discover",
     tuple((s, "simplicity") for s in SEATS)),
    ("r2", "Risk", "r2  ·  over 25 files, 1,500 lines or a risky boundary", "discover",
     tuple(zip(SEATS, BUNDLES))),
    ("r3", "Full red team", "r3  ·  once, for large or high-risk changes", "discover",
     tuple(zip(SEATS, ("attacker", "rollback", "exhaustion", "compatibility")))),
    ("round", "first fix"),
    ("t1", "Triage", "every claim opened at its cited line, then clustered", "gate", ()),
    ("r3p", "Plan", "r3p  ·  every site, test and prediction named", "plan",
     (("sol", "completeness"),)),
    ("f1", "Fix and gates", "red test first, one commit per fix, mutation check", "fix", ()),
    ("r4", "Verification", "r4  ·  four bundles plus a sibling-site check", "verify",
     tuple(zip(SEATS, BUNDLES))),
    ("round", "second fix"),
    ("t2", "Triage", "r4 found a new P1 in a round-one fix", "gate", ()),
    ("r4p", "Plan", "r4p  ·  the new fix is nontrivial", "plan", (("sol", "completeness"),)),
    ("f2", "Fix and gates", "one more commit, gates at baseline or better", "fix", ()),
    ("r5", "Verification", "r5  ·  clean: no new or open P0/P1", "verify", tuple(zip(SEATS, BUNDLES))),
    ("round", "done"),
    ("done", "Seal, push, publish", "receipt, report.md and one PR review", "ok", ()),
]


def chip(t, x, y, w, seat, label, outline=False):
    fill, stroke = ("none", t["line"]) if outline else (t["chip"], "none")
    return "\n".join([
        box(x, y, w, 30, fill, stroke, rx=8),
        f'<circle cx="{x + 14}" cy="{y + 15}" r="5" fill="{t[seat]}"/>',
        text(x + 26, y + 20, label, 13.5, t["text"], 500, MONO),
    ])


def large(t):
    w, spine, cx0, cw, cgap = 1000, 30, 420, 137, 8
    y, rows = 20, []
    launches = 0
    for row in LARGE:
        if row[0] == "round":
            label = row[1].upper()
            rows.append(text(spine + 26, y + 14, label, 11.5, t["faint"], 700, SANS,
                             extra=' letter-spacing="1.5"'))
            rows.append(f'<line x1="{spine + 40 + len(label) * 10}" y1="{y + 10}" x2="{w - 10}" '
                        f'y2="{y + 10}" stroke="{t["line"]}" stroke-width="1"/>')
            y += 30
            continue
        key, title, note, phase, chips = row
        h = 64
        probes = key == "pre"
        filled = t[phase] if chips and not probes else t["bg0"]
        rows.append(f'<circle cx="{spine}" cy="{y + 18}" r="8" fill="{filled}" stroke="{t[phase]}" '
                    f'stroke-width="3"/>')
        rows.append(text(spine + 26, y + 23, title, 18, t["text"], 650))
        rows.append(text(spine + 26, y + 46, note, 14.5, t["muted"]))
        for i, (seat, label) in enumerate(chips):
            rows.append(chip(t, cx0 + i * (cw + cgap), y + 4, cw, seat, label, probes))
        launches += 0 if probes else len(chips)
        if not chips:
            rows.append(text(cx0 + 12, y + 23, "host session", 13.5, t["faint"], 500, MONO))
        y += h
    h = y + 34
    spine_line = (f'<line x1="{spine}" y1="50" x2="{spine}" y2="{y - 46}" stroke="{t["line"]}" '
                  f'stroke-width="2"/>')
    total = text(spine + 26, h - 14, f"{launches} seat launches  ·  every panel seals its receipt before the next edit",
                 14, t["faint"], 600, MONO)
    return svg(w, h, "\n".join([spine_line, *rows, total]), "A large, high-risk review, step by step")


FIGURES = {"hero": hero, "loop": loop, "large-review": large}


def main():
    for name, draw in FIGURES.items():
        for theme, palette in THEMES.items():
            (OUT / f"{name}-{theme}.svg").write_text(draw(palette))


if __name__ == "__main__":
    main()
