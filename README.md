# pdfredact

*[Leggi questo in italiano](README.it.md)*

Redact text in a PDF (true redaction, not just a visual overlay) using
[PyMuPDF](https://pymupdf.readthedocs.io/). Finds occurrences of the specified text/pattern,
applies a redaction annotation, and "burns" it into the page content, physically removing the
underlying text (not recoverable via copy-paste or text extraction).

## Installation

Requires Python 3.10 or later. The only dependency is PyMuPDF, which publishes prebuilt wheels
for Linux, Windows, and macOS (no compiler required).

### With pip

```sh
pip install .
```

or, for development (editable install with test dependencies):

```sh
pip install -e .[test]
```

### With pipx (recommended for a command-line tool)

[pipx](https://pipx.pypa.io/stable/) installs the tool in an isolated virtual environment and
exposes only the `pdfredact` command on `PATH`, without touching the system Python.

**Linux/macOS:**

```sh
python3 -m pip install --user pipx
python3 -m pipx ensurepath
pipx install .          # run from the root of the repository
```

**Windows:**

On Windows it's convenient to install `pipx` via [Scoop](https://scoop.sh/), which also
manages updating Python itself if needed:

```powershell
# If Scoop isn't already installed:
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression

scoop install pipx
pipx ensurepath
```

Then, from the repository folder (in a new terminal, so `ensurepath` takes effect):

```powershell
pipx install .
```

In both cases, after installation the `pdfredact` command is available directly in a new
terminal.

## Usage

```sh
pdfredact input.pdf output.pdf -t "Mario Rossi" -t "CF: ABCDEF"
pdfredact input.pdf output.pdf -r "\bMCNP-\d{4}\b"
pdfredact input.pdf output.pdf -t "Confidential" --case-sensitive
pdfredact input.pdf output.pdf -t "foo" --pages 1,2,5-7
pdfredact input.pdf output.pdf --box "1:56,700,300,730"
pdfredact input.pdf output.pdf -t "foo" --fill-color "#ff0000"
```

Equivalent without installing, from the root of the repository:

```sh
python -m pdfredact input.pdf output.pdf -t "Mario Rossi"
```

### Rectangle coordinates (`--box`)

Format: `PAGE:x0,y0,x1,y1`

- `PAGE` is 1-based (page 1 = first page)
- `x0,y0,x1,y1` in PDF points (72 pt = 1 inch), origin at the top-left (same coordinate
  system returned by `page.search_for()`)
- Corner order doesn't matter: the rectangle is normalized.

### Exit codes

`0` = success, `2` = input/usage error.

## Known limitations

- Document metadata (Author, Title, XMP) and annotation/comment content are not handled,
  since they don't appear in `get_text()`.
- A term split across multiple lines in the PDF layout might not be found.
- Scanned PDFs (image-only, with no extractable text) require OCR upstream: the tool finds
  nothing to redact in that case.

Always verify the output with `pdftotext` and `pdfinfo -meta` before distribution.

## Windows compatibility

The project is tested in CI on Linux, Windows, and macOS (see `.github/workflows/tests.yml`)
and is compatible with Windows without modifications: it only uses `os.path` (no hardcoded
separators), no POSIX-only calls, and `os.path.samefile` has worked correctly on Windows
since Python 3.2.

## Development

```sh
pip install -e .[test]
pytest
pytest tests/test_core.py::test_redact_pdf_literal_term   # single test
```

## AI-assisted development

This project's code, tests, and documentation were developed with the assistance of AI
tools (Claude Code). Every change was reviewed before being published; please report any
issues you find via the project's issue tracker.

## License

[MPL-2.0](COPYING). The repository is [REUSE](https://reuse.software/) compliant; to verify:
`pipx run reuse lint`.
