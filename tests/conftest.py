# SPDX-FileCopyrightText: 2026 Alberto P.
# SPDX-License-Identifier: MPL-2.0
"""Fixture per generare PDF sintetici al volo con PyMuPDF (nessun binario in repo)."""

from __future__ import annotations

import pytest

try:
    import pymupdf as fitz
except ImportError:
    import fitz

PAGE_WIDTH = 595
PAGE_HEIGHT = 842


def _make_pdf(path, pages_text):
    """Crea un PDF con una pagina per ogni stringa di testo in pages_text."""
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
    """Factory fixture: make_pdf(name, [text_pagina_1, text_pagina_2, ...]) -> Path."""

    def _factory(name: str, pages_text: list[str]) -> "object":
        return _make_pdf(tmp_path / name, pages_text)

    return _factory


@pytest.fixture
def sample_pdf(make_pdf):
    """PDF a due pagine con testo noto e un termine ripetuto due volte in pagina 1."""
    return make_pdf(
        "sample.pdf",
        [
            "Nome: Mario Rossi\nCodice: MCNP-1234\nConfidenziale: Mario Rossi ancora",
            "Pagina due: nessun dato sensibile qui, solo testo pubblico.",
        ],
    )


@pytest.fixture
def encrypted_pdf(tmp_path):
    """PDF protetto da password utente (doc.needs_pass True se aperto senza autenticarsi)."""
    path = tmp_path / "encrypted.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.insert_text((72, 100), "Segreto", fontsize=14)
        doc.save(
            str(path),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner-secret",
            user_pw="user-secret",
        )
    finally:
        doc.close()
    return path
