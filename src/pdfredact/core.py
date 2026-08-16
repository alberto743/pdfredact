# SPDX-FileCopyrightText: 2026 Alberto P.
# SPDX-License-Identifier: MPL-2.0
"""
PDF redaction logic (true removal, not just a visual overlay).

Uses PyMuPDF: finds occurrences of the specified text/pattern, applies a
redaction annotation, and "burns" it into the page content with
apply_redactions(), physically removing the underlying text (not
recoverable via copy-paste or text extraction).
"""

import math
import re
import sys
from typing import NoReturn

import yaml

# The `fitz` alias is deprecated and prints a warning to stdout, polluting
# output in pipelines; the canonical name is used instead (guaranteed
# available by the pymupdf>=1.24 dependency floor in pyproject.toml).
import pymupdf as fitz

DEFAULT_FILL_COLOR = "#000000"
DEFAULT_WHOLE_WORD = True


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
    truncated: list[str] = []
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
                # The upper bound is clamped before materializing the range so
                # that '1-999999999' doesn't build a near-billion-element set;
                # record the truncation so it is reported rather than silent.
                if b > n_pages:
                    truncated.append(part)
                pages.update(range(a - 1, min(b, n_pages)))
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
    if truncated:
        print(f"Warning: --pages range(s) {truncated} extend past the last page "
              f"and were truncated (the document has {n_pages} pages)",
              file=sys.stderr)
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
        fail(f"invalid --box format: '{spec}' - expected 4 coordinates "
             f"(x0,y0,x1,y1), got {len(coords)}")
    try:
        values = [float(c) for c in coords]
    except ValueError:
        fail(f"non-numeric coordinates in --box: '{coords_part}'")
    # float() happily accepts 'nan', 'inf' and overflowing literals like
    # '1e400'. PyMuPDF then builds an "infinite"/invalid rectangle that
    # add_redact_annot() accepts but apply_redactions() silently drops: the run
    # would report the box as redacted while leaving the content untouched.
    if not all(math.isfinite(v) for v in values):
        fail(f"non-finite coordinates in --box: '{coords_part}' "
             f"(nan/inf/overflowing values are not valid coordinates)")

    # normalize() mutates the rectangle in-place; don't reassign the result
    # (depending on the PyMuPDF version it may return None instead of self,
    # which would turn `rect` into None and make `rect.is_empty` below crash
    # with an AttributeError instead of the intended fail()).
    rect = fitz.Rect(*values)
    rect.normalize()
    if rect.is_empty:
        fail(f"degenerate --box (zero area): '{spec}' - x0 and x1 (or y0 and y1) coincide")
    return page_no, rect


_HEX_COLOR_RE = re.compile(r"\A[0-9A-Fa-f]{6}\Z")


def parse_fill_color(spec: str) -> tuple[float, float, float]:
    """Convert '#RRGGBB' into an RGB tuple with components in [0, 1]."""
    value = spec.strip()
    if value.startswith("#"):
        value = value[1:]
    # int(x, 16) is lenient: it accepts a sign and surrounding whitespace, so
    # '#-f0000' / '# f0000' / '#+f0000' would pass the length check and yield a
    # component outside [0, 1] - a negative one makes PyMuPDF fail deep inside
    # add_redact_annot() with an opaque TypeError. Validate the digits instead.
    if not _HEX_COLOR_RE.match(value):
        fail(f"invalid --fill-color: '{spec}' (expected hex format '#RRGGBB')")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return r / 255, g / 255, b / 255


_CONFIG_LIST_KEYS = ("text", "regex", "boxes")
_CONFIG_STR_KEYS = ("input", "output", "pages", "fill_color")
_CONFIG_BOOL_KEYS = ("case_sensitive", "whole_word")
_CONFIG_KNOWN_KEYS = frozenset(_CONFIG_LIST_KEYS + _CONFIG_STR_KEYS + _CONFIG_BOOL_KEYS)


def load_config(path: str) -> dict:
    """
    Load and validate a --config YAML file into a dict of option values.

    Every key is optional, but a present key must have the right shape: any
    deviation (unknown key, wrong type, non-mapping top level, unreadable or
    unparsable file) fails loudly rather than being silently ignored or
    coerced, matching the other spec-parsing functions in this module - a
    quietly-dropped or misread config key could mean a PDF that looks
    redacted per its rules but isn't.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        fail(f"config file not found: '{path}'")
    except yaml.YAMLError as exc:
        fail(f"invalid YAML in '{path}': {exc}")
    # A non-UTF-8 file raises UnicodeDecodeError from inside safe_load(); it is a
    # ValueError, not an OSError or a YAMLError, so without this clause it would
    # escape as an opaque traceback with exit code 1 instead of a clean exit 2.
    except UnicodeDecodeError as exc:
        fail(f"config file '{path}' is not valid UTF-8: {exc}")
    except OSError as exc:
        fail(f"could not read config file '{path}': {exc}")

    if data is None:
        return {}
    if not isinstance(data, dict):
        fail(f"invalid config file '{path}': top level must be a mapping of option names to values")

    unknown = sorted(set(data) - _CONFIG_KNOWN_KEYS)
    if unknown:
        fail(f"unknown key(s) in config file '{path}': {unknown}")

    for key in _CONFIG_LIST_KEYS:
        if key in data and (
            not isinstance(data[key], list) or not all(isinstance(v, str) for v in data[key])
        ):
            fail(f"'{key}' in config file '{path}' must be a list of strings")
    for key in _CONFIG_STR_KEYS:
        if key in data and not isinstance(data[key], str):
            # A None value almost always means the value was left unquoted and
            # started with '#' (e.g. `fill_color: #000000`), which YAML reads as
            # a comment and leaves the key empty - point at that directly instead
            # of just restating the expected type.
            hint = (f" (an unquoted '#' starts a YAML comment: write {key}: \"...\")"
                    if data[key] is None else "")
            fail(f"'{key}' in config file '{path}' must be a string{hint}")
    for key in _CONFIG_BOOL_KEYS:
        if key in data and not isinstance(data[key], bool):
            fail(f"'{key}' in config file '{path}' must be true or false")

    return data


def _collapse_ws(text: str) -> str:
    """Collapse every whitespace run (including line breaks) into one space."""
    return " ".join(text.split())


_WORD_CHAR_RE = re.compile(r"\w")


def _needs_word_boundary(term: str) -> tuple[bool, bool]:
    """
    Whether a whole-word match must enforce a boundary before/after `term`,
    based on whether its first/last character is itself a word character.
    Requiring \\b unconditionally on both sides would silently stop matching
    terms that start/end in punctuation once followed by non-word text (\\b
    needs a word/non-word transition) - a false negative, which is worse
    than the over-matching whole-word mode exists to fix. Requiring a
    boundary only on the word-char edges already eliminates the cross-word
    false positives it targets (e.g. "Mario" no longer matches inside
    "Mariotti", nor "Confidential:" inside "NonConfidential:") without that
    risk.
    """
    need_prefix = bool(term) and bool(_WORD_CHAR_RE.match(term[0]))
    need_suffix = bool(term) and bool(_WORD_CHAR_RE.match(term[-1]))
    return need_prefix, need_suffix


def _wrap_whole_word(raw_term: str, escaped_term: str) -> str:
    """
    Anchor `escaped_term` with a regex \\b on each edge that needs one (see
    _needs_word_boundary). This is only a cheap pre-check for whether
    `raw_term` has ANY genuine whole-word occurrence on the page at all -
    the \\b here constrains the *text* search against page.get_text(), not
    the rectangles page.search_for() later returns for the matched string,
    since search_for() is a raw substring search blind to word boundaries.
    The actual per-occurrence filtering happens geometrically afterwards,
    in _filter_whole_word_rects().
    """
    need_prefix, need_suffix = _needs_word_boundary(raw_term)
    prefix = r"\b" if need_prefix else ""
    suffix = r"\b" if need_suffix else ""
    return f"{prefix}{escaped_term}{suffix}"


def _page_lines(page: "fitz.Page") -> list:
    """
    Flatten page.get_text('rawdict') into per-line character lists.

    Each entry is (line_y0, line_y1, chars) where chars holds one
    (x0, x1, height, character) tuple per glyph, sorted left to right.
    Grouping by line keeps the adjacency lookup below proportional to the
    length of the line a match sits on instead of to the whole page, which
    matters when many terms are searched across many pages; plain float
    tuples are used instead of fitz.Rect because that lookup touches every
    candidate character and Rect attribute access is comparatively slow.
    """
    lines = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            chars = []
            for span in line["spans"]:
                for ch in span["chars"]:
                    x0, y0, x1, y1 = ch["bbox"]
                    chars.append((x0, x1, y1 - y0, ch["c"]))
            if not chars:
                continue
            chars.sort()
            lines.append((line["bbox"][1], line["bbox"][3], chars))
    return lines


# Points; float-precision tolerance when aligning a rect edge to a character
# bbox edge. Comfortably smaller than any real character's width, so it can't
# mistakenly skip past a genuinely adjacent character.
_RECT_EDGE_EPS = 0.75

# Fraction of a character's own height (a good proxy for the font size) that
# may separate it from a match and still count as "touching" it. Characters
# within a word are laid out edge to edge, so their gap is ~0; anything wider
# than this is whitespace the producer drew by jumping to a new position
# instead of emitting a space glyph, which is a word boundary just the same.
_MAX_ADJACENT_GAP_RATIO = 0.1


def _adjacent_char(
    lines: list, x: float, y0: float, y1: float, side: str,
) -> str | None:
    """
    Find the character immediately touching position `x` on the given
    `side` ('before' or 'after'), restricted to characters on the same line
    as [y0, y1). Returns None if there is none.

    "None" covers both ends of a line and, crucially, a character separated
    from `x` by a visible gap: PDF producers routinely space out words (table
    columns, form fields, justified text) by moving the text cursor rather
    than by drawing a space glyph, and the extracted character stream then
    has no whitespace at all between them. Treating the nearest character as
    adjacent regardless of distance made every such word look embedded in its
    neighbour, so whole-word mode silently dropped the match and left the text
    unredacted - the exact failure this function exists to prevent.
    """
    best = best_dist = best_limit = None
    for line_y0, line_y1, chars in lines:
        if line_y1 <= y0 or line_y0 >= y1:
            continue  # different line
        # Each line is sorted left to right, so the scan can stop as soon as it
        # is past the position of interest.
        for cx0, cx1, height, c in chars:
            if side == "before":
                if cx0 > x + _RECT_EDGE_EPS:
                    break  # this and every following character start after x
                if cx1 > x + _RECT_EDGE_EPS:
                    continue  # overlaps x instead of ending before it
                dist = x - cx1
            else:
                if cx0 < x - _RECT_EDGE_EPS:
                    continue  # still left of x
                dist = cx0 - x
            if best_dist is None or dist < best_dist:
                best, best_dist = c, dist
                best_limit = max(_RECT_EDGE_EPS, _MAX_ADJACENT_GAP_RATIO * height)
            if side == "after":
                break  # the first character starting at/after x is the nearest
    if best is None or best_dist > best_limit:
        return None
    return best


def _filter_whole_word_rects(
    lines: list, matched_text: str, rects: list["fitz.Rect"],
) -> list["fitz.Rect"]:
    """
    Narrow `rects` (as returned by page.search_for(matched_text)) down to
    genuine whole-word occurrences.

    page.search_for() is a raw substring search over glyph runs: it returns
    a rect for "Mario" wherever those five characters appear contiguously,
    including inside "Mariotti" or "mario2". Whether an occurrence is a
    genuine whole word depends on the actual character immediately before/
    after it on the page - a word character there means the match is
    embedded in a longer word and must be dropped. This has to be checked
    against real per-character positions from page.get_text("rawdict"),
    not the coarser whitespace-delimited tokens page.get_text("words")
    would give: that would wrongly reject "Mario," or "Mario-Luigi", since
    get_text("words") glues trailing punctuation to the preceding word into
    a single token even though a comma or hyphen is a perfectly legitimate
    \\b boundary.
    """
    need_prefix, need_suffix = _needs_word_boundary(matched_text)
    if not (need_prefix or need_suffix):
        return rects
    kept = []
    for r in rects:
        before = _adjacent_char(lines, r.x0, r.y0, r.y1, "before")
        after = _adjacent_char(lines, r.x1, r.y0, r.y1, "after")
        prefix_ok = not need_prefix or before is None or not _WORD_CHAR_RE.match(before)
        suffix_ok = not need_suffix or after is None or not _WORD_CHAR_RE.match(after)
        if prefix_ok and suffix_ok:
            kept.append(r)
    return kept


class PageText:
    """
    Text extractions for one page, computed on first use and reused.

    page.get_text() and page.get_text('rawdict') dominate the cost of a run,
    and every pattern searches the same page: without this the plain text was
    re-extracted once per pattern and the character map once per matched
    string, so a job with many -t terms paid for the same extraction dozens of
    times per page.
    """

    __slots__ = ("_page", "_text", "_lines")

    def __init__(self, page: "fitz.Page") -> None:
        self._page = page
        self._text = None
        self._lines = None

    @property
    def text(self) -> str:
        """The page's plain extracted text (page.get_text())."""
        if self._text is None:
            self._text = self._page.get_text()
        return self._text

    @property
    def lines(self) -> list:
        """The page's characters grouped by line (see _page_lines())."""
        if self._lines is None:
            self._lines = _page_lines(self._page)
        return self._lines


def _warn_not_redacted(page: "fitz.Page", matched: str, reason: str) -> None:
    """Report a pattern match that did not end up producing a redaction."""
    print(f"Warning: matched {matched.strip()!r} on page {page.number + 1} but "
          f"{reason} - it was NOT redacted", file=sys.stderr)


def find_rects_for_pattern(
    page: "fitz.Page",
    pattern: "re.Pattern",
    case_sensitive: bool,
    whole_word: bool = False,
    cache: PageText | None = None,
) -> list["fitz.Rect"]:
    """
    Find the rectangles matching a compiled regex pattern on a page.

    Deduplicates the matched strings before querying search_for() (which
    returns ALL occurrences of that string on the page), avoiding rectangle
    duplication when the same text appears more than once. If
    case_sensitive=True, filters the rectangles by checking the actual text
    inside them, because search_for() is internally case-insensitive. If
    whole_word=True (only meaningful for literal -t terms; -r patterns
    should pass False and keep full manual control via their own \\b),
    further filters the rectangles geometrically via
    _filter_whole_word_rects() to drop occurrences embedded in a longer
    word, since search_for() itself has no notion of word boundaries.

    A matched string that ends up with no rectangle is reported on stderr,
    together with the reason it was dropped: staying silent would mean the
    caller counts fewer redactions than the pattern matched without any way to
    notice the text survived.

    `cache` carries the page's extractions across the several patterns a run
    searches on the same page; when omitted it is built for this call alone.
    """
    if cache is None:
        cache = PageText(page)
    # Empty matches (e.g. regex 'X*' or '.?' that can match an empty
    # string) would make search_for() return None, causing a TypeError.
    unique_strings = dict.fromkeys(
        m.group(0) for m in pattern.finditer(cache.text) if m.group(0).strip()
    )

    rects = []
    for s in unique_strings:
        found = page.search_for(s) or []  # search_for() may return None
        if not found:
            _warn_not_redacted(page, s, "it could not be located on the page")
            continue
        if whole_word:
            found = _filter_whole_word_rects(cache.lines, s, found)
            if not found:
                _warn_not_redacted(
                    page, s, "every occurrence found on the page is part of a longer "
                             "word (whole-word matching is on by default for -t/--text; "
                             "pass --no-whole-word to match substrings too)",
                )
                continue
        if case_sensitive:
            # search_for() returns one rectangle per line the match spans, so a
            # match crossing a line break comes back as several fragments.
            # Comparing each fragment against the whole match string would
            # discard every one of them (silently leaving multi-line matches
            # unredacted), so check that the fragment's text occurs - with the
            # original casing - inside the match.
            needle = _collapse_ws(s)
            found = [
                r for r in found
                if (box := _collapse_ws(page.get_textbox(r))) and box in needle
            ]
            if not found:
                _warn_not_redacted(
                    page, s, "no occurrence found on the page matches its exact case",
                )
                continue
        rects.extend(found)
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
    whole_word: bool = DEFAULT_WHOLE_WORD,
) -> int:
    try:
        doc = fitz.open(input_path)
    except Exception as exc:
        fail(f"could not open '{input_path}': {exc}")

    try:
        # fitz.open() also accepts TXT, EPUB, SVG, CBZ, MOBI and image files,
        # converting them into a document. Redaction annotations are PDF-only,
        # so without this check such an input either dies with an opaque
        # 'ValueError: is no PDF' traceback (exit 1) when something matches, or
        # - worse - reports success and writes a converted PDF when nothing does.
        if not doc.is_pdf:
            fail(f"'{input_path}' is not a PDF (PyMuPDF opened it as another "
                 f"document type, e.g. TXT/EPUB/SVG/image): convert it first")
        # An encrypted PDF opens but its pages aren't accessible: without
        # this check the failure would surface later as an opaque traceback.
        if doc.needs_pass:
            fail(f"'{input_path}' is password protected: decrypt it first "
                 f"(e.g. 'qpdf --password=PW --decrypt in.pdf out.pdf')")
        if doc.page_count == 0:
            fail(f"'{input_path}' has no pages")

        target_pages = (
            parse_page_ranges(page_spec, doc.page_count)
            if page_spec is not None else set(range(doc.page_count))
        )

        # Boxes already specify their own page, so they aren't filtered by --pages
        boxes_by_page: dict[int, list] = {}
        for pno, rect in boxes:
            if pno < 0 or pno >= doc.page_count:
                print(f"Warning: --box on page {pno + 1} ignored "
                      f"(the document has {doc.page_count} pages).", file=sys.stderr)
                continue
            boxes_by_page.setdefault(pno, []).append(rect)

        # A literal term is a regex with special characters escaped: this
        # unifies the search pipeline and ensures --case-sensitive works in
        # both cases. Term and regex patterns are kept in separate lists
        # (rather than one combined list) because whole_word geometric
        # filtering must only ever apply to -t terms: -r patterns keep full
        # manual control over their own boundaries, same as before.
        flags = 0 if case_sensitive else re.IGNORECASE
        term_patterns = [
            re.compile(
                _wrap_whole_word(t, re.escape(t)) if whole_word else re.escape(t), flags,
            )
            for t in terms
        ]
        regex_patterns = []
        for rx in regexes:
            try:
                regex_patterns.append(re.compile(rx, flags))
            except re.error as exc:
                fail(f"invalid regex '{rx}': {exc}")

        total_hits = 0
        for pno in sorted(target_pages | set(boxes_by_page)):
            page = doc[pno]
            rects = []

            if pno in target_pages:
                # One cache per page, shared by every pattern, so the page's
                # text is extracted once instead of once per pattern.
                cache = PageText(page)
                for pattern in term_patterns:
                    rects.extend(
                        find_rects_for_pattern(
                            page, pattern, case_sensitive, whole_word, cache,
                        ),
                    )
                for pattern in regex_patterns:
                    rects.extend(
                        find_rects_for_pattern(page, pattern, case_sensitive, cache=cache),
                    )

            # A box entirely outside the page is accepted by add_redact_annot()
            # but wipes nothing, so counting it as a hit would report a
            # successful redaction for a typo'd coordinate (e.g. 5000 for 500,
            # or bottom-left origin coordinates on a top-left origin page).
            for rect in boxes_by_page.get(pno, []):
                if (rect & page.rect).is_empty:
                    print(f"Warning: --box {tuple(rect)} on page {pno + 1} lies "
                          f"outside the page area {tuple(page.rect)} and "
                          f"redacts nothing", file=sys.stderr)
                    continue
                rects.append(rect)

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
