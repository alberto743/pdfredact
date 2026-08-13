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
    assert "fuori range" in capsys.readouterr().err


# --- parse_box_spec ------------------------------------------------------

def test_parse_box_spec_valid():
    pno, rect = parse_box_spec("1:10,20,100,200")
    assert pno == 0
    assert (rect.x0, rect.y0, rect.x1, rect.y1) == (10, 20, 100, 200)


def test_parse_box_spec_reversed_corners_normalizes():
    """Copre il fix del bug normalize(): non deve sollevare AttributeError."""
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
    assert "Mario Rossi" in _extract_text(sample_pdf)  # originale intatto


def test_redact_pdf_pages_restricts_text_search(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    # "dato sensibile" compare solo in pagina 2; limitando la ricerca a pagina 1 -> 0 hit
    hits = redact_pdf(str(sample_pdf), str(out), ["dato sensibile"], [], [], False, "1")
    assert hits == 0
    assert "dato sensibile" in _extract_text(out, page_index=1)


def test_redact_pdf_box_applies_regardless_of_pages_filter(sample_pdf, tmp_path):
    doc = fitz.open(str(sample_pdf))
    try:
        rect = doc[1].search_for("Pagina due")[0]
    finally:
        doc.close()
    out = tmp_path / "out.pdf"
    # --pages limita la ricerca testuale a pagina 1, ma il --box su pagina 2 si applica comunque
    hits = redact_pdf(str(sample_pdf), str(out), [], [], [(1, rect)], False, "1")
    assert hits == 1
    assert "Pagina due" not in _extract_text(out, page_index=1)


def test_redact_pdf_zero_hits_still_writes_output(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    hits = redact_pdf(str(sample_pdf), str(out), ["stringa-inesistente-xyz"], [], [], False, None)
    assert hits == 0
    assert out.exists()
    assert "Mario Rossi" in _extract_text(out)  # copia non redatta


def test_redact_pdf_encrypted_input_rejected(encrypted_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    with pytest.raises(SystemExit) as exc_info:
        redact_pdf(str(encrypted_pdf), str(out), ["Segreto"], [], [], False, None)
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
