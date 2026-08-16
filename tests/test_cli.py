# SPDX-FileCopyrightText: 2026 Alberto P.
# SPDX-License-Identifier: MPL-2.0
"""
End-to-end CLI tests, invoked as a subprocess (`python -m pdfredact`).

Assumes the package is installed (e.g. `pip install -e .[test]`), so it
exercises exactly the path a real user would use.
"""

from __future__ import annotations

import re
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


def test_cli_default_output_name(sample_pdf):
    result = run_cli(str(sample_pdf), "-t", "Mario Rossi")
    expected_out = sample_pdf.with_name(sample_pdf.stem + "_redacted.pdf")
    assert result.returncode == 0
    assert expected_out.exists()
    assert str(expected_out) in result.stdout


def test_cli_version_flag():
    """--version reports pdfredact.__version__ and exits 0 without needing an
    input file. 'pdfredact' (not '__main__.py') is the expected prog name even
    under 'python -m', which is why the parser sets prog explicitly."""
    result = run_cli("--version")
    assert result.returncode == 0
    assert re.match(r"^pdfredact \d+\.\d+\.\d+", result.stdout.strip())


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


def test_cli_empty_regex_term(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "-r", "   ")
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


@pytest.mark.parametrize("term", ["Mario Rossi", "nonexistent-string-xyz"])
def test_cli_non_pdf_input_rejected(tmp_path, term):
    """A .txt input used to abort with a 'ValueError: is no PDF' traceback and
    exit 1 when the term matched, and to exit 0 announcing a saved file when it
    didn't. Neither is acceptable for a non-PDF input."""
    src = tmp_path / "doc.txt"
    src.write_text("Name: Mario Rossi\n")
    out = tmp_path / "out.pdf"
    result = run_cli(str(src), str(out), "-t", term)
    assert result.returncode == 2
    assert "is not a PDF" in result.stderr
    assert "Traceback" not in result.stderr
    assert not out.exists()


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


def test_cli_zero_hits_hints_at_whole_word(make_pdf, tmp_path):
    """A term that only ever appears inside a longer word finds nothing under
    the default whole-word matching, so the zero-hit warning must name that as
    a likely cause - it is the one cause the user can fix with a flag."""
    pdf = make_pdf("embedded.pdf", ["Mariotti only"])
    out = tmp_path / "out.pdf"
    result = run_cli(str(pdf), str(out), "-t", "Mario")
    assert result.returncode == 0
    assert "--no-whole-word" in result.stderr


def test_cli_invalid_fill_color(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "-t", "Mario Rossi", "--fill-color", "notacolor")
    assert result.returncode == 2
    assert "fill-color" in result.stderr


@pytest.mark.parametrize("color", ["#-f0000", "# f0000"])
def test_cli_out_of_range_fill_color_rejected(sample_pdf, tmp_path, color):
    """These used to slip past validation and reach PyMuPDF, where a negative
    component dies with an opaque TypeError traceback instead of exit 2."""
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "-t", "Mario Rossi", "--fill-color", color)
    assert result.returncode == 2
    assert "fill-color" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_non_finite_box_rejected(sample_pdf, tmp_path):
    """'--box 1:nan,nan,nan,nan' used to exit 0 reporting 1 redacted
    occurrence while leaving the document completely untouched."""
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "--box", "1:nan,nan,nan,nan")
    assert result.returncode == 2
    assert "non-finite" in result.stderr
    assert not out.exists()


def test_cli_off_page_box_warns_and_reports_zero(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "--box", "1:5000,5000,6000,6000")
    assert result.returncode == 0
    assert "outside the page area" in result.stderr
    assert "Occurrences redacted (unique rectangles): 0" in result.stdout
    assert "WARNING" in result.stderr  # unredacted-copy warning fires too


# --- --config -----------------------------------------------------------

def test_cli_config_only_invocation(sample_pdf, tmp_path):
    """input/output/text all come from --config; no positional args at all."""
    out = sample_pdf.with_name(sample_pdf.stem + "_redacted.pdf")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"input: '{sample_pdf}'\n"
        "text:\n"
        "  - Mario Rossi\n"
    )
    result = run_cli("--config", str(config_path))
    assert result.returncode == 0
    assert out.exists()
    assert "Occurrences redacted (unique rectangles): 2" in result.stdout


def test_cli_config_and_cli_terms_merge(sample_pdf, tmp_path):
    """A CLI -t term is added to (not replacing) the config's text list."""
    out = tmp_path / "out.pdf"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "text:\n"
        "  - Mario Rossi\n"
    )
    result = run_cli(str(sample_pdf), str(out), "--config", str(config_path), "-t", "Confidential")
    assert result.returncode == 0
    # "Mario Rossi" appears twice on page 1, "Confidential" once: both selectors count.
    assert "Occurrences redacted (unique rectangles): 3" in result.stdout


def test_cli_pages_cli_overrides_config(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "text:\n"
        "  - Mario Rossi\n"
        "pages: '2'\n"  # page 2 has no "Mario Rossi": would report 0 hits unless overridden
    )
    result = run_cli(str(sample_pdf), str(out), "--config", str(config_path), "--pages", "1")
    assert result.returncode == 0
    assert "Occurrences redacted (unique rectangles): 2" in result.stdout


def test_cli_no_case_sensitive_overrides_config_true(sample_pdf, tmp_path):
    """--no-case-sensitive must be able to force case_sensitive back to false
    even when the config file sets case_sensitive: true, since store_true
    alone could never produce an explicit False to override it with."""
    out = tmp_path / "out.pdf"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "text:\n"
        "  - mario rossi\n"  # wrong case: only matches if case-insensitive
        "case_sensitive: true\n"
    )
    result = run_cli(
        str(sample_pdf), str(out), "--config", str(config_path), "--no-case-sensitive",
    )
    assert result.returncode == 0
    assert "Occurrences redacted (unique rectangles): 2" in result.stdout


def test_cli_whole_word_default_narrows_match(make_pdf, tmp_path):
    """No --whole-word flag passed: the new on-by-default behavior applies,
    so only the standalone "Mario" is redacted, not the one inside
    "Mariotti" or "mario2"."""
    pdf = make_pdf("whole_word.pdf", ["Mariotti likes Mario Rossi and mario2 too."])
    out = tmp_path / "out.pdf"
    result = run_cli(str(pdf), str(out), "-t", "Mario")
    assert result.returncode == 0
    assert "Occurrences redacted (unique rectangles): 1" in result.stdout


def test_cli_no_whole_word_overrides_config_true(make_pdf, tmp_path):
    """--no-whole-word must be able to force whole_word back to false even
    when the config file sets whole_word: true, restoring substring
    matching (all 3 occurrences of "Mario")."""
    pdf = make_pdf("whole_word.pdf", ["Mariotti likes Mario Rossi and mario2 too."])
    out = tmp_path / "out.pdf"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "text:\n"
        "  - Mario\n"
        "whole_word: true\n"
    )
    result = run_cli(
        str(pdf), str(out), "--config", str(config_path), "--no-whole-word",
    )
    assert result.returncode == 0
    assert "Occurrences redacted (unique rectangles): 3" in result.stdout


def test_cli_output_positional_overrides_config_output(sample_pdf, tmp_path):
    cli_out = tmp_path / "cli_out.pdf"
    config_out = tmp_path / "config_out.pdf"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"output: '{config_out}'\n"
        "text:\n"
        "  - Mario Rossi\n"
    )
    result = run_cli(str(sample_pdf), str(cli_out), "--config", str(config_path))
    assert result.returncode == 0
    assert cli_out.exists()
    assert not config_out.exists()


def test_cli_config_unknown_key_fails(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("bogus_key: 1\ntext:\n  - foo\n")
    result = run_cli(str(sample_pdf), str(out), "--config", str(config_path))
    assert result.returncode == 2
    assert "bogus_key" in result.stderr


def test_cli_config_invalid_yaml_fails(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("text: [unclosed\n")
    result = run_cli(str(sample_pdf), str(out), "--config", str(config_path))
    assert result.returncode == 2
    assert "invalid YAML" in result.stderr


def test_cli_config_missing_file_fails(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = run_cli(str(sample_pdf), str(out), "--config", str(tmp_path / "nope.yaml"), "-t", "foo")
    assert result.returncode == 2
    assert "config file not found" in result.stderr


def test_cli_config_wrong_type_fails(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("text: not-a-list\n")
    result = run_cli(str(sample_pdf), str(out), "--config", str(config_path))
    assert result.returncode == 2
    assert "'text'" in result.stderr


def test_cli_config_non_utf8_fails(sample_pdf, tmp_path):
    """UnicodeDecodeError is a ValueError, not an OSError or a YAMLError, so it
    used to escape load_config()'s handlers as a traceback with exit code 1."""
    out = tmp_path / "out.pdf"
    config_path = tmp_path / "config.yaml"
    config_path.write_bytes(b"text:\n  - \xff\xfe Mario\n")
    result = run_cli(str(sample_pdf), str(out), "--config", str(config_path))
    assert result.returncode == 2
    assert "not valid UTF-8" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_config_no_input_anywhere_fails(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("text:\n  - foo\n")
    result = run_cli("--config", str(config_path))
    assert result.returncode == 2
    assert "input PDF is required" in result.stderr
