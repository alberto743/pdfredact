# SPDX-FileCopyrightText: 2026 Alberto P.
# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import re

import pytest

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from pdfredact.core import (
    dedupe_rects,
    find_rects_for_pattern,
    load_config,
    parse_box_spec,
    parse_fill_color,
    parse_page_ranges,
    redact_pdf,
)


# --- parse_page_ranges -------------------------------------------------

def test_parse_page_ranges_basic():
    assert parse_page_ranges("1,2,5-7", 10) == {0, 1, 4, 5, 6}


def test_parse_page_ranges_inverted_range_fails():
    with pytest.raises(SystemExit) as exc_info:
        parse_page_ranges("7-5", 10)
    assert exc_info.value.code == 2


def test_parse_page_ranges_non_integer_fails():
    with pytest.raises(SystemExit) as exc_info:
        parse_page_ranges("abc", 10)
    assert exc_info.value.code == 2


def test_parse_page_ranges_all_out_of_range_fails():
    with pytest.raises(SystemExit) as exc_info:
        parse_page_ranges("50", 10)
    assert exc_info.value.code == 2


def test_parse_page_ranges_partial_out_of_range_warns(capsys):
    result = parse_page_ranges("1,50", 10)
    assert result == {0}
    assert "out-of-range" in capsys.readouterr().err


def test_parse_page_ranges_huge_upper_bound_does_not_hang():
    """A range like '1-999999999' must be clamped to n_pages before being
    materialized, not turned into a near-billion-element set/range."""
    result = parse_page_ranges("1-999999999", 10)
    assert result == set(range(10))


def test_parse_page_ranges_truncated_range_warns(capsys):
    """Clamping a range's upper bound must be reported, exactly like a
    single out-of-range page number is, instead of passing silently."""
    assert parse_page_ranges("2-99", 3) == {1, 2}
    assert "truncated" in capsys.readouterr().err


# --- parse_box_spec ------------------------------------------------------

def test_parse_box_spec_valid():
    pno, rect = parse_box_spec("1:10,20,100,200")
    assert pno == 0
    assert (rect.x0, rect.y0, rect.x1, rect.y1) == (10, 20, 100, 200)


def test_parse_box_spec_reversed_corners_normalizes():
    """Covers the normalize() fix: must not raise AttributeError."""
    pno, rect = parse_box_spec("2:100,200,10,20")
    assert pno == 1
    assert (rect.x0, rect.y0, rect.x1, rect.y1) == (10, 20, 100, 200)
    assert not rect.is_empty


def test_parse_box_spec_degenerate_fails():
    with pytest.raises(SystemExit) as exc_info:
        parse_box_spec("1:10,20,10,200")
    assert exc_info.value.code == 2


def test_parse_box_spec_missing_colon_fails():
    with pytest.raises(SystemExit) as exc_info:
        parse_box_spec("10,20,100,200")
    assert exc_info.value.code == 2


def test_parse_box_spec_wrong_coord_count_fails():
    with pytest.raises(SystemExit) as exc_info:
        parse_box_spec("1:10,20,100")
    assert exc_info.value.code == 2


def test_parse_box_spec_non_numeric_fails():
    with pytest.raises(SystemExit) as exc_info:
        parse_box_spec("1:a,b,c,d")
    assert exc_info.value.code == 2


@pytest.mark.parametrize("spec", [
    "1:nan,nan,nan,nan",
    "1:inf,0,100,100",
    "1:0,0,-inf,100",
    "1:0,0,1e400,100",  # overflows to inf
])
def test_parse_box_spec_non_finite_fails(spec):
    """float() accepts 'nan'/'inf'; the resulting rectangle is neither empty
    nor valid, so PyMuPDF accepts the annotation and then drops it - the run
    would report the box as redacted while leaving the page untouched."""
    with pytest.raises(SystemExit) as exc_info:
        parse_box_spec(spec)
    assert exc_info.value.code == 2


# --- parse_fill_color ------------------------------------------------------

def test_parse_fill_color_valid():
    assert parse_fill_color("#ff0000") == pytest.approx((1.0, 0.0, 0.0))


def test_parse_fill_color_without_hash():
    assert parse_fill_color("00ff00") == pytest.approx((0.0, 1.0, 0.0))


def test_parse_fill_color_invalid_fails():
    with pytest.raises(SystemExit) as exc_info:
        parse_fill_color("red")
    assert exc_info.value.code == 2


@pytest.mark.parametrize("spec", ["#-f0000", "# f0000", "#+f0000", "#ff 000", "##ff0000"])
def test_parse_fill_color_rejects_lenient_int_forms(spec):
    """int(x, 16) tolerates signs and surrounding whitespace, so these used to
    pass the length check and yield a component outside [0, 1] (a negative one
    crashes PyMuPDF with an opaque TypeError inside add_redact_annot)."""
    with pytest.raises(SystemExit) as exc_info:
        parse_fill_color(spec)
    assert exc_info.value.code == 2


# --- load_config -------------------------------------------------------

def test_load_config_valid_roundtrip(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "input: in.pdf\n"
        "output: out.pdf\n"
        "text:\n"
        "  - Mario Rossi\n"
        "regex:\n"
        "  - '\\bMCNP-\\d{4}\\b'\n"
        "boxes:\n"
        "  - '1:56,700,300,730'\n"
        "case_sensitive: true\n"
        "whole_word: false\n"
        "pages: '1,2,5-7'\n"
        "fill_color: '#ff0000'\n"
    )
    config = load_config(str(config_path))
    assert config == {
        "input": "in.pdf",
        "output": "out.pdf",
        "text": ["Mario Rossi"],
        "regex": ["\\bMCNP-\\d{4}\\b"],
        "boxes": ["1:56,700,300,730"],
        "case_sensitive": True,
        "whole_word": False,
        "pages": "1,2,5-7",
        "fill_color": "#ff0000",
    }


def test_load_config_missing_file_fails():
    with pytest.raises(SystemExit) as exc_info:
        load_config("/nonexistent/config.yaml")
    assert exc_info.value.code == 2


def test_load_config_empty_file_returns_empty_dict(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("")
    assert load_config(str(config_path)) == {}


def test_load_config_invalid_yaml_fails(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("text: [unclosed\n")
    with pytest.raises(SystemExit) as exc_info:
        load_config(str(config_path))
    assert exc_info.value.code == 2


def test_load_config_non_mapping_top_level_fails(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("- just\n- a\n- list\n")
    with pytest.raises(SystemExit) as exc_info:
        load_config(str(config_path))
    assert exc_info.value.code == 2


def test_load_config_unknown_key_fails(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("bogus_key: 1\n")
    with pytest.raises(SystemExit) as exc_info:
        load_config(str(config_path))
    assert exc_info.value.code == 2


@pytest.mark.parametrize("key,bad_value", [
    ("text", "not-a-list"),
    ("text", "[1, 2]"),
    ("regex", "not-a-list"),
    ("boxes", "not-a-list"),
    ("input", "[1, 2]"),
    ("pages", "[1, 2]"),
    ("fill_color", "[1, 2]"),
    ("case_sensitive", "not-a-bool"),
    ("whole_word", "not-a-bool"),
])
def test_load_config_wrong_type_fails(tmp_path, key, bad_value):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"{key}: {bad_value}\n")
    with pytest.raises(SystemExit) as exc_info:
        load_config(str(config_path))
    assert exc_info.value.code == 2


def test_load_config_non_utf8_fails(tmp_path):
    """A non-UTF-8 file raises UnicodeDecodeError inside yaml.safe_load(). It is
    a ValueError, so it used to escape every handler and abort with a traceback
    and exit code 1 instead of the documented exit 2."""
    config_path = tmp_path / "config.yaml"
    config_path.write_bytes(b"text:\n  - \xff\xfe Mario\n")
    with pytest.raises(SystemExit) as exc_info:
        load_config(str(config_path))
    assert exc_info.value.code == 2


def test_load_config_list_of_non_strings_fails(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("text:\n  - 1\n  - 2\n")
    with pytest.raises(SystemExit) as exc_info:
        load_config(str(config_path))
    assert exc_info.value.code == 2


# --- find_rects_for_pattern / dedupe_rects ---------------------------------

def test_find_rects_for_pattern_repeated_term(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    try:
        pattern = re.compile(re.escape("Mario Rossi"))
        rects = find_rects_for_pattern(doc[0], pattern, case_sensitive=False)
    finally:
        doc.close()
    assert len(rects) == 2


def test_find_rects_for_pattern_empty_match_no_crash(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    try:
        pattern = re.compile(r"Z*")
        rects = find_rects_for_pattern(doc[0], pattern, case_sensitive=False)
    finally:
        doc.close()
    assert rects == []


def test_find_rects_for_pattern_case_sensitive_keeps_multiline_match(make_pdf):
    """search_for() returns one rect per line a match spans. Comparing each
    fragment against the whole match string used to discard all of them, so
    --case-sensitive silently left every multi-line match unredacted."""
    pdf = make_pdf("multiline.pdf", ["AAA\nBBB\nKEEP"])
    doc = fitz.open(str(pdf))
    try:
        pattern = re.compile(r"AAA.*BBB", re.S)
        assert len(find_rects_for_pattern(doc[0], pattern, case_sensitive=True)) == 2
    finally:
        doc.close()


def test_find_rects_for_pattern_case_sensitive_still_rejects_wrong_case(sample_pdf):
    """The multi-line fix must not weaken the case check itself."""
    doc = fitz.open(str(sample_pdf))
    try:
        pattern = re.compile(re.escape("mario rossi"))
        assert find_rects_for_pattern(doc[0], pattern, case_sensitive=True) == []
    finally:
        doc.close()


def test_dedupe_rects_removes_duplicates():
    r1 = fitz.Rect(0, 0, 10, 10)
    r2 = fitz.Rect(0, 0, 10, 10)
    r3 = fitz.Rect(5, 5, 15, 15)
    assert len(dedupe_rects([r1, r2, r3])) == 2


# --- redact_pdf end-to-end ---------------------------------------------

def _extract_text(pdf_path, page_index=0):
    doc = fitz.open(str(pdf_path))
    try:
        return doc[page_index].get_text()
    finally:
        doc.close()


def test_redact_pdf_literal_term(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    hits = redact_pdf(str(sample_pdf), str(out), ["Mario Rossi"], [], [], False, None)
    assert hits == 2
    assert "Mario Rossi" not in _extract_text(out)


def test_redact_pdf_regex(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    hits = redact_pdf(str(sample_pdf), str(out), [], [r"MCNP-\d{4}"], [], False, None)
    assert hits == 1
    assert "MCNP-1234" not in _extract_text(out)


def test_redact_pdf_case_insensitive_default(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    hits = redact_pdf(str(sample_pdf), str(out), ["mario rossi"], [], [], False, None)
    assert hits == 2


def test_redact_pdf_case_sensitive_blocks_mismatched_case(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    hits = redact_pdf(str(sample_pdf), str(out), ["mario rossi"], [], [], True, None)
    assert hits == 0
    assert "Mario Rossi" in _extract_text(sample_pdf)  # original untouched


def test_redact_pdf_pages_restricts_text_search(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    # "sensitive data" only appears on page 2; restricting the search to page 1 -> 0 hits
    hits = redact_pdf(str(sample_pdf), str(out), ["sensitive data"], [], [], False, "1")
    assert hits == 0
    assert "sensitive data" in _extract_text(out, page_index=1)


def test_redact_pdf_whole_word_default_skips_substring_match(make_pdf, tmp_path):
    pdf = make_pdf("whole_word.pdf", ["Mariotti likes Mario Rossi and mario2 too."])
    out = tmp_path / "out.pdf"
    hits = redact_pdf(str(pdf), str(out), ["Mario"], [], [], False, None)
    assert hits == 1
    text = _extract_text(out)
    # "Mariotti" and "mario2" stay fully intact; only the standalone "Mario"
    # is redacted, so the substring "Mario" survives once (as the prefix of
    # "Mariotti") rather than disappearing entirely.
    assert "Mariotti" in text
    assert "mario2" in text
    assert text.count("Mario") == 1


def test_redact_pdf_whole_word_false_matches_substring(make_pdf, tmp_path):
    pdf = make_pdf("whole_word.pdf", ["Mariotti likes Mario Rossi and mario2 too."])
    out = tmp_path / "out.pdf"
    hits = redact_pdf(str(pdf), str(out), ["Mario"], [], [], False, None, whole_word=False)
    assert hits == 3
    text = _extract_text(out)
    assert "Mario" not in text
    assert "mario2" not in text


def test_redact_pdf_whole_word_punctuation_edge_no_false_negative(make_pdf, tmp_path):
    pdf = make_pdf(
        "whole_word_punct.pdf",
        ["Confidential: top secret. NonConfidential: not this one."],
    )
    out = tmp_path / "out.pdf"
    hits = redact_pdf(str(pdf), str(out), ["Confidential:"], [], [], False, None)
    assert hits == 1
    text = _extract_text(out)
    # "NonConfidential:" stays fully intact; only the standalone occurrence of
    # "Confidential:" is redacted, so the substring survives once (as part of
    # "NonConfidential:") rather than disappearing entirely.
    assert "NonConfidential:" in text
    assert text.count("Confidential:") == 1


def test_redact_pdf_box_applies_regardless_of_pages_filter(sample_pdf, tmp_path):
    doc = fitz.open(str(sample_pdf))
    try:
        rect = doc[1].search_for("Page two")[0]
    finally:
        doc.close()
    out = tmp_path / "out.pdf"
    # --pages restricts text search to page 1, but --box on page 2 still applies
    hits = redact_pdf(str(sample_pdf), str(out), [], [], [(1, rect)], False, "1")
    assert hits == 1
    assert "Page two" not in _extract_text(out, page_index=1)


def test_redact_pdf_case_sensitive_multiline_actually_removes_text(make_pdf, tmp_path):
    pdf = make_pdf("multiline.pdf", ["AAA\nBBB\nKEEP"])
    out = tmp_path / "out.pdf"
    hits = redact_pdf(str(pdf), str(out), [], [r"(?s)AAA.*BBB"], [], True, None)
    assert hits == 2
    text = _extract_text(out)
    assert "AAA" not in text and "BBB" not in text
    assert "KEEP" in text


def test_redact_pdf_off_page_box_is_not_counted_as_a_hit(sample_pdf, tmp_path, capsys):
    """add_redact_annot() accepts a box outside the page and then wipes
    nothing: counting it would report a successful redaction for a typo'd
    coordinate, hiding the fact that the content is still there."""
    out = tmp_path / "out.pdf"
    hits = redact_pdf(
        str(sample_pdf), str(out), [], [], [(0, fitz.Rect(5000, 5000, 6000, 6000))],
        False, None,
    )
    assert hits == 0
    assert "outside the page area" in capsys.readouterr().err


def test_redact_pdf_partially_off_page_box_still_applies(sample_pdf, tmp_path):
    """Only a box with *no* overlap is dropped; a partially overlapping one
    must still redact the part that lands on the page."""
    doc = fitz.open(str(sample_pdf))
    try:
        rect = doc[0].search_for("Mario Rossi")[0]
    finally:
        doc.close()
    out = tmp_path / "out.pdf"
    overlapping = fitz.Rect(rect.x0, rect.y0, rect.x1 + 10_000, rect.y1)
    hits = redact_pdf(str(sample_pdf), str(out), [], [], [(0, overlapping)], False, None)
    assert hits == 1
    assert "Mario Rossi" not in _extract_text(out).split("\n")[0]


def test_redact_pdf_zero_hits_still_writes_output(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    hits = redact_pdf(str(sample_pdf), str(out), ["nonexistent-string-xyz"], [], [], False, None)
    assert hits == 0
    assert out.exists()
    assert "Mario Rossi" in _extract_text(out)  # unredacted copy


def test_redact_pdf_negative_box_page_rejected(sample_pdf, tmp_path, capsys):
    """A negative page index must be ignored with a warning, not silently
    redact the last page via Python's negative indexing."""
    out = tmp_path / "out.pdf"
    rect = fitz.Rect(0, 0, 10, 10)
    hits = redact_pdf(str(sample_pdf), str(out), [], [], [(-1, rect)], False, None)
    assert hits == 0
    assert "ignored" in capsys.readouterr().err


def test_redact_pdf_empty_pages_spec_fails_loudly(sample_pdf, tmp_path):
    """An explicit but empty --pages spec must fail like other malformed
    specs, not silently fall back to 'all pages'."""
    out = tmp_path / "out.pdf"
    with pytest.raises(SystemExit) as exc_info:
        redact_pdf(str(sample_pdf), str(out), ["Mario Rossi"], [], [], False, "")
    assert exc_info.value.code == 2


@pytest.mark.parametrize("terms", [["Mario Rossi"], ["nonexistent-string-xyz"]])
def test_redact_pdf_non_pdf_input_rejected(tmp_path, terms):
    """fitz.open() also opens TXT/EPUB/SVG/images. Redaction annotations are
    PDF-only, so such an input used to die with 'ValueError: is no PDF' (exit 1)
    when something matched and - worse - to report success while writing a
    converted PDF when nothing did. Both paths must fail with exit 2."""
    src = tmp_path / "doc.txt"
    src.write_text("Name: Mario Rossi\n")
    out = tmp_path / "out.pdf"
    with pytest.raises(SystemExit) as exc_info:
        redact_pdf(str(src), str(out), terms, [], [], False, None)
    assert exc_info.value.code == 2
    assert not out.exists()


def test_redact_pdf_encrypted_input_rejected(encrypted_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    with pytest.raises(SystemExit) as exc_info:
        redact_pdf(str(encrypted_pdf), str(out), ["Secret"], [], [], False, None)
    assert exc_info.value.code == 2


def test_redact_pdf_custom_fill_color_applied(sample_pdf, tmp_path):
    doc = fitz.open(str(sample_pdf))
    try:
        rect = doc[0].search_for("Mario Rossi")[0]
    finally:
        doc.close()
    out = tmp_path / "out.pdf"
    hits = redact_pdf(
        str(sample_pdf), str(out), ["Mario Rossi"], [], [], False, None,
        fill_color=(1.0, 0.0, 0.0),
    )
    assert hits == 2

    doc2 = fitz.open(str(out))
    try:
        pix = doc2[0].get_pixmap(clip=rect, dpi=72)
    finally:
        doc2.close()
    cx, cy = pix.width // 2, pix.height // 2
    r, g, b = pix.pixel(cx, cy)[:3]
    assert r > 200 and g < 50 and b < 50


# --- package version ---------------------------------------------------

def test_version_is_not_hardcoded_placeholder():
    """__version__ is resolved dynamically via importlib.metadata, not a literal."""
    import pdfredact

    assert re.match(r"^\d+\.\d+\.\d+", pdfredact.__version__)
