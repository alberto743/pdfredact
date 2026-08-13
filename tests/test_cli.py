# SPDX-FileCopyrightText: 2026 Alberto P.
# SPDX-License-Identifier: MPL-2.0
"""
Test end-to-end della CLI, invocata come sottoprocesso (`python -m pdfredact`).

Presuppongono che il pacchetto sia installato (es. `pip install -e .[test]`),
così da esercitare esattamente il percorso che userebbe un utente reale.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pdfredact", *args],
        capture_output=True,
        text=True,
    )


def test_cli_success_exit_code_and_output(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "-t", "Mario Rossi")
    assert result.returncode == 0
    assert out.exists()
    assert "Occorrenze oscurate" in result.stdout


def test_cli_missing_input_file(tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(tmp_path / "nope.pdf"), str(out), "-t", "foo")
    assert result.returncode == 2
    assert "non trovato" in result.stderr


def test_cli_input_equals_output(sample_pdf):
    result = run_cli(str(sample_pdf), str(sample_pdf), "-t", "Mario Rossi")
    assert result.returncode == 2
    assert "coincidono" in result.stderr


def test_cli_missing_output_directory(sample_pdf, tmp_path):
    out = tmp_path / "does-not-exist" / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "-t", "Mario Rossi")
    assert result.returncode == 2
    assert "directory di output inesistente" in result.stderr


def test_cli_empty_text_term(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "-t", "   ")
    assert result.returncode == 2
    assert "stringa vuota" in result.stderr


def test_cli_no_selectors_given(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out))
    assert result.returncode == 2
    assert "specificare almeno un termine" in result.stderr


def test_cli_invalid_regex(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "-r", "(unclosed")
    assert result.returncode == 2
    assert "regex non valida" in result.stderr


def test_cli_encrypted_input_rejected(encrypted_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(encrypted_pdf), str(out), "-t", "Segreto")
    assert result.returncode == 2
    assert "protetto da password" in result.stderr


def test_cli_zero_hits_warns_on_stderr(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "-t", "stringa-inesistente-xyz")
    assert result.returncode == 0
    assert "ATTENZIONE" in result.stderr
    assert out.exists()


def test_cli_invalid_fill_color(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "-t", "Mario Rossi", "--fill-color", "notacolor")
    assert result.returncode == 2
    assert "fill-color" in result.stderr
