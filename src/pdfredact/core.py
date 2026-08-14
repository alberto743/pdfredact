# SPDX-FileCopyrightText: 2026 Alberto P.
# SPDX-License-Identifier: MPL-2.0
"""
PDF redaction logic (true removal, not just a visual overlay).

Uses PyMuPDF: finds occurrences of the specified text/pattern, applies a
redaction annotation, and "burns" it into the page content with
apply_redactions(), physically removing the underlying text (not
recoverable via copy-paste or text extraction).
"""

from __future__ import annotations

import re
import sys
from typing import NoReturn

# The `fitz` alias is deprecated and prints a warning to stdout, polluting
# output in pipelines; the canonical name is preferred when available.
try:
    import pymupdf as fitz
except ImportError:  # PyMuPDF < 1.24
    import fitz


def fail(message: str) -> NoReturn:
    """Abort with an input/usage error (exit code 2)."""
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(2)


def parse_page_ranges(spec: str, n_pages: int) -> set[int]:
    """
    Convert '1,2,5-7' into a set of 0-based page indices.

    Explicitly validates every token: non-integer numbers, pages <= 0, and
    reversed ranges raise an error instead of propagating a raw ValueError
    or silently producing an empty set (which would lead to an unredacted
    PDF).
    """
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part.lstrip("-"):
                a_str, b_str = part.split("-", 1)
                a, b = int(a_str), int(b_str)
                if a < 1 or b < 1:
                    raise ValueError
                if a > b:
                    fail(f"reversed page range in --pages: '{part}' "
                         f"(expected 'lower-higher', e.g. '5-7')")
                pages.update(range(a - 1, b))
            else:
                n = int(part)
                if n < 1:
                    raise ValueError
                pages.add(n - 1)
        except ValueError:
            fail(f"invalid value in --pages: '{part}' "
                 f"(expected integer page numbers >= 1, e.g. '1,2,5-7')")

    valid = {p for p in pages if 0 <= p < n_pages}
    out_of_range = sorted(p + 1 for p in pages - valid)
    if out_of_range:
        print(f"Warning: out-of-range pages ignored (the document has "
              f"{n_pages} pages): {out_of_range}", file=sys.stderr)
    if not valid:
        fail(f"--pages selects no valid page (document has {n_pages} pages)")
    return valid


def parse_box_spec(spec: str) -> tuple[int, "fitz.Rect"]:
    """
    Convert 'PAGE:x0,y0,x1,y1' into (0-based page index, fitz.Rect).

    Normalizes the rectangle: a box with corners in reversed order (e.g.
    x1 < x0) would otherwise be "empty" for PyMuPDF and silently ignored,
    producing an unredacted PDF while still reporting the occurrence as
    redacted.
    """
    if ":" not in spec:
        fail(f"invalid --box format: '{spec}' (expected 'PAGE:x0,y0,x1,y1')")

    page_part, coords_part = spec.split(":", 1)
    try:
        page_no = int(page_part.strip()) - 1
    except ValueError:
        fail(f"invalid page number in --box: '{page_part}' (expected an integer >= 1)")
    if page_no < 0:
        fail(f"invalid page number in --box: '{page_part}' (pages start at 1)")

    coords = [c.strip() for c in coords_part.split(",")]
    if len(coords) != 4:
        fail(f"invalid --box format: '{spec}' — expected 4 coordinates "
             f"(x0,y0,x1,y1), got {len(coords)}")
    try:
        values = [float(c) for c in coords]
    except ValueError:
        fail(f"non-numeric coordinates in --box: '{coords_part}'")

    # normalize() mutates the rectangle in-place; don't reassign the result
    # (depending on the PyMuPDF version it may return None instead of self,
    # which would turn `rect` into None and make `rect.is_empty` below crash
    # with an AttributeError instead of the intended fail()).
    rect = fitz.Rect(*values)
    rect.normalize()
    if rect.is_empty:
        fail(f"degenerate --box (zero area): '{spec}' — x0 and x1 (or y0 and y1) coincide")
    return page_no, rect


def parse_fill_color(spec: str) -> tuple[float, float, float]:
    """Convert '#RRGGBB' into an RGB tuple with components in [0, 1]."""
    value = spec.strip().lstrip("#")
    if len(value) != 6:
        fail(f"invalid --fill-color: '{spec}' (expected hex format '#RRGGBB')")
    try:
        r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        fail(f"invalid --fill-color: '{spec}' (expected hex format '#RRGGBB')")
    return r / 255, g / 255, b / 255


def find_rects_for_pattern(
    page: "fitz.Page", pattern: "re.Pattern", case_sensitive: bool
) -> list["fitz.Rect"]:
    """
    Find the rectangles matching a compiled regex pattern on a page.

    Deduplicates the matched strings before querying search_for() (which
    returns ALL occurrences of that string on the page), avoiding rectangle
    duplication when the same text appears more than once. If
    case_sensitive=True, filters the rectangles by checking the actual text
    inside them, because search_for() is internally case-insensitive.
    """
    text = page.get_text()
    # Empty matches (e.g. regex 'X*' or '.?' that can match an empty
    # string) would make search_for() return None, causing a TypeError.
    unique_strings = dict.fromkeys(
        m.group(0) for m in pattern.finditer(text) if m.group(0).strip()
    )

    rects = []
    for s in unique_strings:
        found = page.search_for(s)
        if not found:  # None or empty list
            continue
        for r in found:
            if case_sensitive and page.get_textbox(r).strip() != s.strip():
                continue
            rects.append(r)
    return rects


def dedupe_rects(rects: list["fitz.Rect"], precision: int = 2) -> list["fitz.Rect"]:
    """Remove duplicate/coincident rectangles (same coordinates rounded)."""
    seen = set()
    unique = []
    for r in rects:
        key = tuple(round(v, precision) for v in (r.x0, r.y0, r.x1, r.y1))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def redact_pdf(
    input_path: str,
    output_path: str,
    terms: list[str],
    regexes: list[str],
    boxes: list[tuple[int, "fitz.Rect"]],
    case_sensitive: bool,
    page_spec: str | None,
    fill_color: tuple[float, float, float] = (0, 0, 0),
) -> int:
    try:
        doc = fitz.open(input_path)
    except Exception as exc:
        fail(f"could not open '{input_path}': {exc}")

    try:
        # An encrypted PDF opens but its pages aren't accessible: without
        # this check the failure would surface later as an opaque traceback.
        if doc.needs_pass:
            fail(f"'{input_path}' is password protected: decrypt it first "
                 f"(e.g. 'qpdf --password=PW --decrypt in.pdf out.pdf')")
        if doc.page_count == 0:
            fail(f"'{input_path}' has no pages")

        target_pages = (
            parse_page_ranges(page_spec, doc.page_count)
            if page_spec else set(range(doc.page_count))
        )

        # Boxes already specify their own page, so they aren't filtered by --pages
        boxes_by_page: dict[int, list] = {}
        for pno, rect in boxes:
            if pno >= doc.page_count:
                print(f"Warning: --box on page {pno + 1} ignored "
                      f"(the document has {doc.page_count} pages).", file=sys.stderr)
                continue
            boxes_by_page.setdefault(pno, []).append(rect)

        # A literal term is a regex with special characters escaped: this
        # unifies the search pipeline and ensures --case-sensitive works in
        # both cases.
        flags = 0 if case_sensitive else re.IGNORECASE
        compiled_patterns = [re.compile(re.escape(t), flags) for t in terms]
        for rx in regexes:
            try:
                compiled_patterns.append(re.compile(rx, flags))
            except re.error as exc:
                fail(f"invalid regex '{rx}': {exc}")

        total_hits = 0
        for pno in sorted(target_pages | set(boxes_by_page)):
            page = doc[pno]
            rects = []

            if pno in target_pages:
                for pattern in compiled_patterns:
                    rects.extend(find_rects_for_pattern(page, pattern, case_sensitive))

            rects.extend(boxes_by_page.get(pno, []))
            rects = dedupe_rects(rects)
            if not rects:
                continue

            for r in rects:
                page.add_redact_annot(r, fill=fill_color)
            # PDF_REDACT_IMAGE_PIXELS also zeroes out the pixels of covered images
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
            total_hits += len(rects)

        try:
            # garbage=4 removes unreferenced orphan objects (streams, fonts).
            # It does NOT remove document metadata: see the warning in main().
            doc.save(output_path, garbage=4, deflate=True, clean=True)
        except Exception as exc:
            fail(f"could not write '{output_path}': {exc}")

        return total_hits
    finally:
        doc.close()
