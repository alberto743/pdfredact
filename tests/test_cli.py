# SPDX-FileCopyrightText: 2026 Alberto P.
# SPDX-License-Identifier: MPL-2.0
"""
End-to-end CLI tests, invoked as a subprocess (`python -m pdfredact`).

Assumes the package is installed (e.g. `pip install -e .[test]`), so it
exercises exactly the path a real user would use.
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
    assert "Occurrences redacted" in result.stdout


def test_cli_missing_input_file(tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(tmp_path / "nope.pdf"), str(out), "-t", "foo")
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_cli_input_equals_output(sample_pdf):
    result = run_cli(str(sample_pdf), str(sample_pdf), "-t", "Mario Rossi")
    assert result.returncode == 2
    assert "same file" in result.stderr


def test_cli_missing_output_directory(sample_pdf, tmp_path):
    out = tmp_path / "does-not-exist" / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "-t", "Mario Rossi")
    assert result.returncode == 2
    assert "output directory does not exist" in result.stderr


def test_cli_empty_text_term(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "-t", "   ")
    assert result.returncode == 2
    assert "empty string" in result.stderr


def test_cli_no_selectors_given(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out))
    assert result.returncode == 2
    assert "specify at least one term" in result.stderr


def test_cli_invalid_regex(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "-r", "(unclosed")
    assert result.returncode == 2
    assert "invalid regex" in result.stderr


def test_cli_encrypted_input_rejected(encrypted_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(encrypted_pdf), str(out), "-t", "Secret")
    assert result.returncode == 2
    assert "password protected" in result.stderr


def test_cli_zero_hits_warns_on_stderr(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "-t", "nonexistent-string-xyz")
    assert result.returncode == 0
    assert "WARNING" in result.stderr
    assert out.exists()


def test_cli_invalid_fill_color(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "-t", "Mario Rossi", "--fill-color", "notacolor")
    assert result.returncode == 2
    assert "fill-color" in result.stderr
