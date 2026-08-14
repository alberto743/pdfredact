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


# --- parse_fill_color ------------------------------------------------------

def test_parse_fill_color_valid():
    assert parse_fill_color("#ff0000") == pytest.approx((1.0, 0.0, 0.0))


def test_parse_fill_color_without_hash():
    assert parse_fill_color("00ff00") == pytest.approx((0.0, 1.0, 0.0))


def test_parse_fill_color_invalid_fails():
    with pytest.raises(SystemExit) as exc_info:
        parse_fill_color("red")
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
