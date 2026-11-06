#!/usr/bin/env python3
"""Figure 1 of the Lancet Digital Health manuscript: the verbal autopsy
pathway in DigitVA version 3.

Writes figure1_pathway.svg (text kept as text) and, when rsvg-convert is on
PATH, figure1_pathway.pdf and figure1_pathway.png (300 dpi).  Stdlib only;
Pillow is used for text measurement when available.  Every item carries a
``source`` naming the manuscript sentence or Table 1 row that supports it
(scripts/build_digitva_ldh_manuscript.py).

Run:  python3 docs/manuscript/figures/make_figure1_pathway.py
"""
from __future__ import annotations

import html
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "figure1_pathway"

# Geometry in points; 180 mm two-column width.
WIDTH_MM = 180
W = WIDTH_MM * 72 / 25.4  # 510.24 pt
MARGIN = 4
FONT = "Helvetica, Arial, sans-serif"
BODY = 7.0
TITLE = 8.0
SMALL = 7.0
LINE = 8.6  # body line height

# Okabe-Ito, colour-blind safe: three step groups plus grey for the band.
COLOURS = {  # (stroke and header, box tint, header text)
    "collect": ("#0072B2", "#DCEBF6", "white"),
    "code": ("#009E73", "#D5F0E7", "white"),
    "report": ("#E69F00", "#FCEBCB", "black"),
    "band": ("#6E6E6E", "#F0F0F0", "black"),
}

GROUPS = [
    ("collect", "Notify and collect", [0, 1, 2]),
    ("code", "Decision support, coding and review", [3, 4, 5]),
    ("report", "Report", [6]),
]

# weight: relative column width.  source: manuscript sentence or Table 1 row.
STEPS = [
    {
        "title": "Death notification",
        "weight": 1.0,
        "items": [
            ("Death register by health unit",
             "Results: 'A death can be entered in a death register by a health worker, assigned to an interviewer in the responsible health unit'; Table 1 'Death notification' v3"),
            ("Possible-duplicate check",
             "Results: 'Possible duplicate registrations are flagged by matching names, telephone numbers and health identifiers'; Table 1 'Death notification' v3"),
            ("Interviewer assigned",
             "Results: 'assigned to an interviewer in the responsible health unit and followed until the interview is done'; Table 1 'Death notification' v3"),
        ],
    },
    {
        "title": "Interview",
        "weight": 1.3,
        "items": [
            ("ODK Collect, web browser, or DigitVA Collect Android app (works offline)",
             "Results: 'Interviews are collected in ODK Collect ..., entered in a web browser, or collected in the DigitVA Collect Android app, which works without a network'; Table 1 'Interview' v3"),
            ("WHO 2022 questionnaire with DigitVA layers switched on per project",
             "Results: 'The WHO 2022 questionnaire is the base, and each project switches on DigitVA layers'; Table 1 'Questionnaire' v3"),
            ("Narrative text, photographs, audio, medical documents",
             "Results: 'Photographs of medical documents and of the written narrative, and audio-recorded narratives, are stored with the interview'; Table 1 'Narrative and documents'"),
        ],
    },
    {
        "title": "Transfer",
        "weight": 1.0,
        "items": [
            ("ODK synchronisation to the server",
             "Results: 'collected in ODK Collect and synchronised to the server'; Table 1 'Interview' v2/v3"),
            ("Unsent interviews kept in an encrypted store on the phone",
             "Results: 'keeps unsent interviews in an encrypted store on the phone'; Table 1 'Access and privacy' v3 'encrypted phone store'"),
            ("Signed, encrypted transfer files from sites without a network",
             "Table 1 'Interview' v3: 'signed, encrypted transfer files from sites without a network'"),
        ],
    },
    {
        "title": "SmartVA",
        "weight": 0.75,
        "items": [
            ("Run on every interview",
             "Results: 'SmartVA is run on every interview, on the server and on the phone'"),
            ("On the server and on the phone",
             "Results: same sentence; Table 1 'Decision support' v3"),
        ],
    },
    {
        "title": "Physician coding",
        "weight": 1.25,
        "items": [
            ("Masked step 1, then step 2 with SmartVA shown; or one step with SmartVA shown (set per project)",
             "Results: 'a project chooses between this masked two-step coding and a single step with SmartVA output shown'; Table 1 'Decision support' v3 'masking set per project'"),
            ("ICD-10 or ICD-11 with the WHO mortality rules",
             "Results: 'the cause is recorded in ICD-10 or ICD-11 ... the underlying cause is selected with the WHO mortality rules (DORIS)'; Table 1 'Cause coding' v3"),
            ("Same screens on web and phone, offline",
             "Results: 'the same coding screens run on the web and on the phone, with or without a network'; Table 1 'Cause coding' v3"),
        ],
    },
    {
        "title": "Review and recoding",
        "weight": 1.0,
        "items": [
            ("Reviewer allocated for quality assurance",
             "Results: 'A reviewer can be allocated for quality assurance'"),
            ("Recoding window for correction",
             "Results: 'a recoding window allows correction'; Table 1 'Cause coding' v2 'reviewer and recoding'"),
        ],
    },
    {
        "title": "Reporting",
        "weight": 1.25,
        "items": [
            ("Cause groups: WHO 2022 VA, SRS, CMEA10",
             "Results: 'Each ICD-10 and ICD-11 code is mapped to the cause groups of the WHO 2022 verbal autopsy list, and the same deaths can be reported with the Sample Registration System or CMEA10 cause lists'; Table 1 'Codes and cause groups' v3"),
            ("Dashboards by health unit; flags for no interview within 60 days or no coding within 15 days",
             "Results: 'Dashboards show deaths, interviews and coding progress by health-system unit, and flag deaths not interviewed within 60 days and interviews not coded within 15 days'; Table 1 'Monitoring' v3"),
            ("Plain-language questions on aggregate counts",
             "Results: 'Data managers can ask questions in plain language ... run only on aggregate counts within the user's access'; Table 1 'Analysis' v3"),
        ],
    },
]

RETURN_ARROW = (
    "Incomplete interview sent back to the interviewer for revision",
    "Results: 'A coder or reviewer can send an incomplete interview back to the interviewer for revision'; Table 1 'Narrative and documents' v3",
)

BAND_TITLE = "Across all steps"
BAND = [
    ("Access", "Relationship-based access along the health-system hierarchy",
     "Results: 'relationship-based access control: what a user can see and do follows their relationship to the health-system hierarchy'; Table 1 'Access and privacy' v3"),
    ("Personal data", "Identifiers held by project, shown only to health-system staff with a grant, encrypted at rest",
     "Results: 'Personal identifiers are shown only to staff inside the health system who hold a grant in that project ... Death registration numbers are encrypted at rest'; Table 1 'Access and privacy' v3 'personal data by project'"),
    ("Configuration", "Per project: questionnaire layers, consent notice, coding workflow, cause-group scheme",
     "Results: 'Projects are set up through configuration rather than changes to code: questionnaire layers, option lists, the consent notice, the coding workflow ... and the cause-group scheme'"),
    ("Training", "Training project with pseudonymised cases, weekly synthetic demonstration, public demonstration site, standalone phone mode",
     "Results: training paragraph; Table 1 'Training and demonstration' v3"),
    ("Open", "Public help pages, cause-group schemes and code-to-cause mapping; open-source code",
     "Results: 'Searchable help pages, cause-group schemes and the full code-to-cause mapping are public'; Methods: 'open-source software under the MIT licence'"),
]

VERSION_BARS = [
    ("Version 3: every step", [0, 6],
     "Table 1 v3 column; Results 'DigitVA supports each step of the verbal autopsy pathway'"),
    ("Versions 1 and 2: ODK Collect interview onward; reviewer and recoding from version 2", [1, 6],
     "Table 1 'Death notification' v1/v2 'None'; 'Interview' v1/v2 'ODK Collect'; 'Cause coding' v2 'reviewer and recoding'"),
]


# ---------------------------------------------------------------- text width
def _measure():
    try:
        from PIL import ImageFont

        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 100)

        def width(text, size):
            return font.getlength(text) * size / 100

        return width
    except Exception:  # Pillow or the font is missing: average-width estimate
        return lambda text, size: len(text) * size * 0.5


text_width = _measure()


def wrap(text, size, max_w):
    """Greedy word wrap; a hyphenated word may break after its hyphen."""
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if text_width(trial, size) <= max_w:
            cur = trial
            continue
        head, sep, tail = word.partition("-")
        if sep and text_width(f"{cur} {head}-".strip(), size) <= max_w:
            lines.append(f"{cur} {head}-".strip())
            cur = tail
        elif cur:
            lines.append(cur)
            cur = word
        else:
            cur = word  # single word wider than the box; checked visually
    if cur:
        lines.append(cur)
    return lines


def esc(s):
    return html.escape(s, quote=False)


# ---------------------------------------------------------------------- draw
def build():
    out = []
    gap = 7  # between step boxes, holds the arrow
    inner = W - 2 * MARGIN - gap * (len(STEPS) - 1)
    unit = inner / sum(s["weight"] for s in STEPS)
    xs, x = [], MARGIN
    for s in STEPS:
        w = s["weight"] * unit
        xs.append((x, w))
        x += w + gap

    pad = 3.5
    # Pre-wrap step text so all boxes get the same height.
    for s, (_, w) in zip(STEPS, xs):
        s["lines"] = [wrap(t, BODY, w - 2 * pad - 5) for t, _ in s["items"]]
        s["title_lines"] = wrap(s["title"], TITLE, w - 2 * pad - 10)
    n_lines = max(sum(len(l) for l in s["lines"]) + 0.35 * (len(s["lines"]) - 1)
                  for s in STEPS)
    n_title = max(len(s["title_lines"]) for s in STEPS)
    head_h = 4 + n_title * (TITLE + 1.6)
    box_h = head_h + 3 + n_lines * LINE + 3

    y_group = MARGIN + SMALL
    y_box = y_group + 5
    y_box_end = y_box + box_h

    # Group labels with a rule under them.
    for key, label, cols in GROUPS:
        stroke = COLOURS[key][0]
        x0 = xs[cols[0]][0]
        x1 = xs[cols[-1]][0] + xs[cols[-1]][1]
        out.append(f'<text x="{x0:.1f}" y="{y_group:.1f}" font-size="{SMALL}" '
                   f'font-weight="bold" fill="{stroke}">{esc(label)}</text>')
        out.append(f'<line x1="{x0:.1f}" y1="{y_group + 2:.1f}" x2="{x1:.1f}" '
                   f'y2="{y_group + 2:.1f}" stroke="{stroke}" stroke-width="0.8"/>')

    # Step boxes.
    colour_of = {}
    for key, _, cols in GROUPS:
        for c in cols:
            colour_of[c] = COLOURS[key]
    for i, (s, (x, w)) in enumerate(zip(STEPS, xs)):
        stroke, fill, head_text = colour_of[i]
        out.append(f'<rect x="{x:.1f}" y="{y_box:.1f}" width="{w:.1f}" height="{box_h:.1f}" '
                   f'rx="2" fill="{fill}" stroke="{stroke}" stroke-width="0.8"/>')
        out.append(f'<rect x="{x:.1f}" y="{y_box:.1f}" width="{w:.1f}" height="{head_h:.1f}" '
                   f'rx="2" fill="{stroke}"/>')
        # square off the bottom corners of the header strip
        out.append(f'<rect x="{x:.1f}" y="{y_box + head_h - 2:.1f}" width="{w:.1f}" height="2" fill="{stroke}"/>')
        # number circle
        cx, cy = x + pad + 3.2, y_box + head_h / 2
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.7" fill="white"/>')
        out.append(f'<text x="{cx:.1f}" y="{cy + 2.5:.1f}" font-size="7" font-weight="bold" '
                   f'text-anchor="middle" fill="{stroke}">{i + 1}</text>')
        ty = y_box + 3 + TITLE
        for tl in s["title_lines"]:
            out.append(f'<text x="{x + pad + 8.5:.1f}" y="{ty:.1f}" font-size="{TITLE}" '
                       f'font-weight="bold" fill="{head_text}">{esc(tl)}</text>')
            ty += TITLE + 1.6
        yy = y_box + head_h + 3 + BODY
        for lines in s["lines"]:
            out.append(f'<text x="{x + pad:.1f}" y="{yy:.1f}" font-size="{BODY}" fill="#000">•</text>')
            for ln in lines:
                out.append(f'<text x="{x + pad + 5:.1f}" y="{yy:.1f}" font-size="{BODY}" '
                           f'fill="#000">{esc(ln)}</text>')
                yy += LINE
            yy += 0.35 * LINE
        # forward arrow
        if i < len(STEPS) - 1:
            ax0, ax1 = x + w + 0.8, x + w + gap - 0.8
            ay = y_box + head_h / 2
            out.append(f'<line x1="{ax0:.1f}" y1="{ay:.1f}" x2="{ax1 - 2:.1f}" y2="{ay:.1f}" '
                       f'stroke="#000" stroke-width="0.8"/>')
            out.append(f'<polygon points="{ax1:.1f},{ay:.1f} {ax1 - 2.6:.1f},{ay - 1.8:.1f} '
                       f'{ax1 - 2.6:.1f},{ay + 1.8:.1f}" fill="#000"/>')

    # Return arrow: from the coding and review boxes back to the interview box.
    y_ret = y_box_end + 11
    x_from = xs[4][0] + xs[4][1] / 2  # physician coding
    x_from2 = xs[5][0] + xs[5][1] / 2  # review
    x_to = xs[1][0] + xs[1][1] / 2  # interview
    dash = 'stroke="#000" stroke-width="0.7" stroke-dasharray="2.2,1.4" fill="none"'
    out.append(f'<path d="M{x_from2:.1f},{y_box_end:.1f} V{y_ret:.1f} H{x_to:.1f} V{y_box_end + 3:.1f}" {dash}/>')
    out.append(f'<path d="M{x_from:.1f},{y_box_end:.1f} V{y_ret:.1f}" {dash}/>')
    out.append(f'<polygon points="{x_to:.1f},{y_box_end + 0.5:.1f} {x_to - 1.8:.1f},{y_box_end + 3.3:.1f} '
               f'{x_to + 1.8:.1f},{y_box_end + 3.3:.1f}" fill="#000"/>')
    label, _ = RETURN_ARROW
    lx = (x_to + x_from) / 2
    out.append(f'<text x="{lx:.1f}" y="{y_ret - 1.8:.1f}" font-size="{SMALL}" text-anchor="middle" '
               f'fill="#000">{esc(label)}</text>')

    # Version coverage bars.
    y_ver = y_ret + 7
    for label, (c0, c1), _ in VERSION_BARS:
        x0 = xs[c0][0]
        x1 = xs[c1][0] + xs[c1][1]
        out.append(f'<line x1="{x0:.1f}" y1="{y_ver:.1f}" x2="{x1:.1f}" y2="{y_ver:.1f}" '
                   f'stroke="#000" stroke-width="1.2"/>')
        for xe in (x0, x1):
            out.append(f'<line x1="{xe:.1f}" y1="{y_ver - 2:.1f}" x2="{xe:.1f}" y2="{y_ver + 2:.1f}" '
                       f'stroke="#000" stroke-width="1.2"/>')
        out.append(f'<text x="{x0 + 3:.1f}" y="{y_ver + SMALL + 2.2:.1f}" font-size="{SMALL}" '
                   f'fill="#000">{esc(label)}</text>')
        y_ver += SMALL + 9

    # Cross-cutting band.
    stroke, fill, _ = COLOURS["band"]
    y_band_title = y_ver + 3
    out.append(f'<text x="{MARGIN:.1f}" y="{y_band_title:.1f}" font-size="{SMALL}" '
               f'font-weight="bold" fill="{stroke}">{esc(BAND_TITLE)}</text>')
    out.append(f'<line x1="{MARGIN:.1f}" y1="{y_band_title + 2:.1f}" x2="{W - MARGIN:.1f}" '
               f'y2="{y_band_title + 2:.1f}" stroke="{stroke}" stroke-width="0.8"/>')
    y_band = y_band_title + 5
    bgap = 5
    bw = (W - 2 * MARGIN - bgap * (len(BAND) - 1)) / len(BAND)
    wrapped = [(h, wrap(t, BODY, bw - 2 * pad)) for h, t, _ in BAND]
    band_h = TITLE + 3 + max(len(l) for _, l in wrapped) * LINE + 3
    for k, (head, lines) in enumerate(wrapped):
        bx = MARGIN + k * (bw + bgap)
        out.append(f'<rect x="{bx:.1f}" y="{y_band:.1f}" width="{bw:.1f}" height="{band_h:.1f}" '
                   f'rx="2" fill="{fill}" stroke="{stroke}" stroke-width="0.8"/>')
        out.append(f'<text x="{bx + pad:.1f}" y="{y_band + 2.5 + BODY:.1f}" font-size="{BODY}" '
                   f'font-weight="bold" fill="#000">{esc(head)}</text>')
        yy = y_band + 2.5 + BODY + LINE
        for ln in lines:
            out.append(f'<text x="{bx + pad:.1f}" y="{yy:.1f}" font-size="{BODY}" fill="#000">{esc(ln)}</text>')
            yy += LINE
    H = y_band + band_h + MARGIN

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH_MM}mm" '
        f'height="{H * 25.4 / 72:.2f}mm" viewBox="0 0 {W:.2f} {H:.2f}" '
        f'font-family="{FONT}">\n'
        f'<title>The verbal autopsy pathway in DigitVA version 3</title>\n'
        f'<rect width="{W:.2f}" height="{H:.2f}" fill="white"/>\n'
        + "\n".join(out) + "\n</svg>\n"
    )
    return svg


def main():
    svg_path = OUT.with_suffix(".svg")
    svg_path.write_text(build(), encoding="utf-8")
    print("wrote", svg_path)
    conv = shutil.which("rsvg-convert")
    if not conv:
        print("rsvg-convert not found: PDF and PNG not produced")
        return
    dpi = 300
    px = round(WIDTH_MM / 25.4 * dpi)
    subprocess.run([conv, "-f", "pdf", "-o", str(OUT.with_suffix(".pdf")), str(svg_path)], check=True)
    subprocess.run([conv, "-f", "png", "-w", str(px), "--dpi-x", str(dpi), "--dpi-y", str(dpi),
                    "-o", str(OUT.with_suffix(".png")), str(svg_path)], check=True)
    try:  # rsvg-convert does not write the pHYs chunk; stamp 300 dpi
        from PIL import Image

        png = OUT.with_suffix(".png")
        Image.open(png).save(png, dpi=(dpi, dpi))
    except Exception:
        pass
    print("wrote", OUT.with_suffix(".pdf"), OUT.with_suffix(".png"))


if __name__ == "__main__":
    main()
