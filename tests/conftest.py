# SPDX-FileCopyrightText: 2026 Alberto P.
# SPDX-License-Identifier: MPL-2.0
"""Fixtures to generate synthetic PDFs on the fly with PyMuPDF (no binaries in the repo)."""

from __future__ import annotations

import pytest

try:
    import pymupdf as fitz
except ImportError:
    import fitz

PAGE_WIDTH = 595
PAGE_HEIGHT = 842


def _make_pdf(path, pages_text):
    """Create a PDF with one page per text string in pages_text."""
    doc = fitz.open()
    try:
        for text in pages_text:
            page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            page.insert_text((72, 100), text, fontsize=14)
        doc.save(str(path))
    finally:
        doc.close()
    return path


@pytest.fixture
def make_pdf(tmp_path):
    """Factory fixture: make_pdf(name, [page_1_text, page_2_text, ...]) -> Path."""

    def _factory(name: str, pages_text: list[str]) -> "object":
        return _make_pdf(tmp_path / name, pages_text)

    return _factory


@pytest.fixture
def sample_pdf(make_pdf):
    """Two-page PDF with known text and a term repeated twice on page 1."""
    return make_pdf(
        "sample.pdf",
        [
            "Name: Mario Rossi\nCode: MCNP-1234\nConfidential: Mario Rossi again",
            "Page two: no sensitive data here, only public text.",
        ],
    )


@pytest.fixture
def encrypted_pdf(tmp_path):
    """PDF protected with a user password (doc.needs_pass True when opened without auth)."""
    path = tmp_path / "encrypted.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.insert_text((72, 100), "Secret", fontsize=14)
        doc.save(
            str(path),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner-secret",
            user_pw="user-secret",
        )
    finally:
        doc.close()
    return path
