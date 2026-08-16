# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An installable Python CLI package (`pdfredact`) that performs *true* PDF redaction (not just
visual overlay) using PyMuPDF. It finds text via literal terms, regex patterns, and/or explicit
page rectangles, then burns those areas out with `apply_redactions()` so the underlying
text/pixels are physically removed and not recoverable via copy-paste or text extraction.

The package (code, CLI messages, docstrings, comments) is entirely in English. `README.it.md` is
the sole Italian-language file in the repo — a translation of `README.md`, kept in sync with it.
Keep new user-facing strings and comments in English for consistency.

Licensed MPL-2.0, REUSE-compliant (every source file carries an SPDX header; see "License /
REUSE" below). Hosted at `https://github.com/alberto743/pdfredact`.

## Setup

```sh
pip install -e .[test]
```

Requires Python 3.10+ (bumped from the original 3.9 floor once 3.9 reached end-of-life).
`core.py`/`cli.py` use `list[str]`, `set[int]`, `X | None`-style hints directly as real runtime
expressions — `X | Y` union syntax (PEP 604) needs 3.10 at runtime, which is why neither file
carries a `from __future__ import annotations` (PEP 563) anymore: that import used to be the
only thing letting those hints run on 3.9, and dropping the 3.9 floor made it dead weight. Don't
reintroduce it as a stylistic default; postponed evaluation is opt-in only, not automatic in any
current Python version (the plan to make it default in 3.10 was reverted). `match`/`case` and
`zip(strict=)` are fair game now too; `except*` still needs 3.11, so don't add it without bumping
the floor again. Runtime dependencies are `pymupdf` and `pyyaml` (for `--config`), both of which
ship prebuilt wheels for Linux/Windows/macOS — no compiler needed anywhere. Build backend is
Hatchling (`[build-system]` in `pyproject.toml`); package discovery is explicit via
`[tool.hatch.build.targets.wheel] packages = ["src/pdfredact"]`.

Also installable with `pipx install .` (see README.md for full pipx/Windows-via-Scoop
instructions) — this is the intended way for end users to get the `pdfredact` command without
touching a system Python environment.

`pdfredact.__version__` is resolved dynamically at import time via
`importlib.metadata.version("pdfredactcli")` (falls back to `"0.0.0"` if the package isn't
installed) rather than being hardcoded in `__init__.py` — `pyproject.toml`'s `[project] version`
is the single source of truth.

## Running

```sh
pdfredact input.pdf output.pdf -t "Mario Rossi" -t "CF: ABCDEF"
pdfredact input.pdf output.pdf -r "\bMCNP-\d{4}\b"
pdfredact input.pdf output.pdf -t "Confidential" --case-sensitive
pdfredact input.pdf output.pdf -t "Mario" --no-whole-word   # also matches "Mariotti"
pdfredact input.pdf output.pdf -t "foo" --pages 1,2,5-7
pdfredact input.pdf output.pdf --box "1:56,700,300,730"
pdfredact input.pdf output.pdf -t "foo" --fill-color "#ff0000"
pdfredact input.pdf -t "Mario Rossi"              # writes input_redacted.pdf
pdfredact --config job.yaml
pdfredact input.pdf output.pdf --config rules.yaml -t "extra one-off term"
pdfredact --version
```

`output` is an optional positional argument; when omitted it defaults to
`<input-stem>_redacted.pdf` in the input's own directory. `input` is optional too, as long as
it's supplied via `--config` instead (see `load_config()` below).

Or without installing: `python -m pdfredact ...` from the repo root.

Exit codes: `0` success, `2` input/usage error (raised via the `fail()` helper in
`src/pdfredact/core.py`, which prints to stderr and calls `sys.exit(2)`).

## Testing

```sh
pytest                                              # full suite
pytest tests/test_core.py::test_redact_pdf_literal_term   # single test
```

`tests/conftest.py` generates synthetic PDFs on the fly via PyMuPDF (`page.insert_text()`) —
there are no binary PDF fixtures checked into the repo. The `make_positioned_pdf` fixture places
each text run at explicit coordinates, which is how the table/form layouts that broke whole-word
matching are reproduced (words separated by a cursor jump, with no space glyph between them).
`test_core.py` unit-tests `src/pdfredact/core.py` functions directly; `test_cli.py` drives the
CLI as a subprocess (`python -m pdfredact`) to check exit codes and stderr messages end-to-end.
`test_cli.py` assumes the package is installed (`pip install -e .[test]`) before running.
`conftest.py`/`test_core.py` import PyMuPDF the same way `core.py` does — plain `import pymupdf
as fitz`, no fallback and no `from __future__ import annotations` — since the 3.10 floor and the
`pymupdf>=1.24` dependency floor make both unnecessary here too.

## Architecture

`src/pdfredact/` is split into:

- **`core.py`** — all redaction logic, no argparse/CLI concerns. Structured as a pipeline:
  1. **Spec parsing** — `parse_page_ranges()` (`"1,2,5-7"` → 0-based page index set),
     `parse_box_spec()` (`"PAGE:x0,y0,x1,y1"` → `(page_index, fitz.Rect)`, normalized so
     reversed corners still work), `parse_fill_color()` (`"#RRGGBB"` → RGB float tuple). All
     three fail loudly (`fail()` → exit 2) on malformed input rather than silently producing an
     empty/no-op selection, since a silent no-op would mean a PDF that looks redacted but isn't.
     Two input classes that *look* well-formed are rejected for exactly that reason: non-finite
     `--box` coordinates (`float()` accepts `nan`/`inf`/`1e400`, and the resulting rect is
     neither `is_empty` nor `is_valid`, so PyMuPDF takes the annotation and then drops it), and
     `--fill-color` values that only pass because `int(x, 16)` tolerates signs and whitespace
     (`"#-f0000"` → a negative component → opaque `TypeError` inside `add_redact_annot`) —
     hence the strict `_HEX_COLOR_RE` match instead of a bare length check. `parse_page_ranges()`
     still clamps a range's upper bound before materializing it (so `1-999999999` can't build a
     billion-element set) but now warns that it truncated, matching how a bare out-of-range page
     number is reported. `load_config()` (for `--config`) applies the same philosophy to a whole
     YAML file at once: `yaml.safe_load()`, then reject anything that isn't a mapping, any key
     outside the known set (`input`, `output`, `text`, `regex`, `boxes`, `case_sensitive`,
     `whole_word`, `pages`, `fill_color`), and any value of the wrong type (e.g. `text: "foo"`
     instead of `text: ["foo"]`) — no silent coercion, since a lazily-typed config key could
     otherwise mean an option is quietly dropped instead of applied. A string-typed key whose
     value came back `None` gets a targeted hint about YAML comments, because `fill_color:
     #000000` (unquoted) is the one mistake this format invites: YAML reads the value as a
     comment and leaves the key empty. Note the `UnicodeDecodeError` clause in
     `load_config()`'s `except` chain: a non-UTF-8 config file raises it from inside
     `yaml.safe_load()`, and it's a `ValueError` — neither an `OSError` nor a `yaml.YAMLError` —
     so without it the file escaped as a traceback with exit 1 instead of a clean exit 2.
     `DEFAULT_FILL_COLOR = "#000000"` is a
     shared constant so `cli.py`'s help text and its config-merge fallback can't drift apart.
  2. **Match finding** — `find_rects_for_pattern()` runs a compiled regex against
     `page.get_text()`, deduplicates the matched strings, then uses `page.search_for()` to get
     rects. Literal terms (`-t`) are compiled as `re.escape()`'d patterns so they share the same
     regex pipeline as `-r`. Because `search_for()` is case-insensitive regardless of pattern
     flags, case-sensitive mode is enforced with a secondary `get_textbox()` check — that check
     compares *whitespace-collapsed containment* (`box in needle`), not equality, because
     `search_for()` returns one rect per line a match spans; equality dropped every fragment of a
     multi-line match and silently left it unredacted. A matched string that resolves to no rect
     at all is reported on stderr rather than skipped quietly, with the reason it was dropped
     (not found / all occurrences embedded in a longer word / no occurrence in the right case) —
     a single generic "could not locate it on the page" pointed at the wrong cause for two of
     the three.

     **Whole-word matching** (`-t` only, on by default, `DEFAULT_WHOLE_WORD`) is enforced twice,
     because the two halves of the pipeline disagree about what a word is. The regex against
     `get_text()` gets `\b` wrapped around the edges of the term that are themselves word
     characters (`_wrap_whole_word()`/`_needs_word_boundary()`; wrapping unconditionally would
     stop `"Confidential:"` from ever matching, a false negative). But that is only a
     page-level pre-check: `search_for()` is a raw substring search with no notion of word
     boundaries, so each returned rect is then filtered geometrically by
     `_filter_whole_word_rects()`, which looks up the character physically adjacent to the rect
     via `_adjacent_char()` over `get_text("rawdict")` positions. `-r` patterns never go through
     either step — they keep manual control via their own `\b`.

     `_adjacent_char()` treats a character as adjacent only if it (nearly) touches the rect
     edge: within `_RECT_EDGE_EPS`, or `_MAX_ADJACENT_GAP_RATIO` (0.1) of the character's own
     height, which stands in for the font size. The gap limit is not cosmetic. PDF producers
     routinely separate words by moving the text cursor instead of drawing a space glyph (table
     columns, form fields, right-aligned values), so the extracted character stream reads
     `Name:MarioRossi` with no whitespace anywhere; taking the nearest character regardless of
     distance made every such word look embedded in its neighbour and whole-word mode dropped
     the match — leaving the term unredacted on exactly the form-like PDFs this tool is aimed
     at. Characters inside a real word are laid out edge to edge (gap ~0), so the threshold
     separates the two cases with a wide margin. Don't widen it to the width of a space: a
     separately-drawn run that starts exactly where the previous one ends is still one word.

     `PageText` caches a page's `get_text()` and `_page_lines()` results for the whole run over
     that page. Before it, the plain text was re-extracted once per pattern and the character
     map once per *matched string*, which dominated the runtime of any job with several `-t`
     terms. `_page_lines()` groups characters by line and sorts each line left to right so the
     adjacency scan is bounded by the line, not the page, and can break early.
  3. **Redaction** (`redact_pdf()`) — per page, collects rects from text search (only on pages in
     `--pages`) plus explicit `--box` rects (which apply regardless of `--pages`, and are dropped
     with a warning if they don't intersect `page.rect`, since an off-page box wipes nothing but
     would otherwise still be counted as a hit), dedupes via
     `dedupe_rects()`, then calls `add_redact_annot(fill=fill_color)` +
     `apply_redactions(images=PDF_REDACT_IMAGE_PIXELS)` so covered image pixels are wiped too,
     not just annotated over.
  4. Saves with `garbage=4, deflate=True, clean=True` to strip orphaned objects — note this does
     *not* touch document metadata (Author, Title, XMP) or annotation/comment content, since
     those don't appear in `get_text()`. `cli.py` prints an explicit warning about this scope
     limitation.
- **`cli.py`** — argparse setup and `main()`. Both `input` and `output` are optional positionals
  (`nargs="?"`); when `output` is omitted it's derived from `input` right after the input-exists
  check (`os.path.splitext(input_path)` → `<stem>_redacted.pdf`), so the existing
  samefile/output-dir validation still runs against the derived path uniformly, with no
  special-casing. `prog="pdfredact"` is set explicitly on the parser so usage and `--version`
  output read `pdfredact` under `python -m pdfredact` too, where argparse would otherwise derive
  `__main__.py` from `sys.argv[0]`; `-V/--version` is an `action="version"` flag fed from
  `pdfredact.__version__`, so it resolves through `importlib.metadata` and needs no input file.
  When `--config FILE.yaml` is given, `core.load_config()` loads it into a dict
  and `main()` merges it with the parsed CLI args: list options (`terms`/`regexes`/`box_specs`)
  are the CLI list **plus** the config's list; scalar options (`input`/`output`/`case_sensitive`/
  `whole_word`/`pages`/`fill_color`) take the CLI value if it was explicitly passed, else the
  config's value, else the hardcoded default. Detecting "explicitly passed" requires the CLI's
  own defaults for those scalar flags to be `None` instead of a real value (`--fill-color` used
  to default to `"#000000"` directly; `--case-sensitive` used to be `store_true`, defaulting to
  `False`) — otherwise a config value could never be told apart from "user didn't pass this
  flag" and the merge couldn't apply config-only fallback correctly. `--case-sensitive` is now
  `argparse.BooleanOptionalAction` (default `None`), which also generates a `--no-case-sensitive`
  counterpart — without it, a config file's `case_sensitive: true` could never be overridden back
  to `false` from the command line, since plain `store_true` has no way to produce an explicit
  `False`. `--whole-word` is the same kind of flag for the same reason (default `None`, with a
  generated `--no-whole-word`, falling back to `DEFAULT_WHOLE_WORD`). Validates input/output
  paths up front (input exists, output dir exists, input != output to avoid destroying the
  original in-place) before
  calling into `core.redact_pdf()`. The zero-hit `WARNING` appends a whole-word hint when the run
  used `-t` terms with whole-word matching on, since that is now a likely cause of an empty
  result. This is the `pdfredact` console-script entry point
  (`[project.scripts]` in `pyproject.toml`).
- **`__main__.py`** — enables `python -m pdfredact`.

Known limitation callouts (already handled/documented in code, don't "fix" without discussion):
- Zero-hit runs still write an output file, but print a `WARNING` that it's an unredacted copy —
  this is intentional so scripted/pipeline usage doesn't silently mask failures.
- Encrypted PDFs (`doc.needs_pass`) are rejected with a clear message rather than failing deeper
  in the pipeline with an opaque traceback. The `not doc.is_pdf` check right before it exists
  for the same reason and must stay ahead of it in `redact_pdf()`: `fitz.open()` also accepts
  TXT/EPUB/SVG/CBZ/image files and converts them into a document, but redaction annotations are
  PDF-only, so such an input used to die with `ValueError: is no PDF` (exit 1) when something
  matched and — worse — to exit 0 announcing a saved file when nothing did. Encrypted PDFs still
  report "password protected" because `is_pdf` is `True` for them.
- Two subtle bugs were fixed when this was packaged (see git history): `fail()`'s
  `NoReturn` annotation was previously an unimported forward-reference string, and
  `parse_box_spec()` used to reassign `rect = fitz.Rect(...).normalize()`, which would silently
  turn `rect` into `None` on PyMuPDF versions where `normalize()` mutates in place and returns
  `None`, crashing with `AttributeError` instead of a graceful `fail()`. `normalize()` is now
  called for its side effect only, never reassigned.

## Windows compatibility

Verified compatible: only `os.path` is used (no hardcoded separators), no POSIX-only calls, and
`os.path.samefile` has worked correctly on Windows since Python 3.2. `.github/workflows/tests.yml`
runs the full suite on `windows-latest` (and macOS) alongside Linux on every push/PR, and
`.github/workflows/wheels.yml` builds+tests the wheel on `windows-latest` too.
All CLI output is plain ASCII English, so there's no `cmd.exe` code-page/encoding footnote to
worry about (unlike the old Italian, accented-character messages this project used to print).

## License / REUSE

MPL-2.0. Full license text lives at `LICENSES/MPL-2.0.txt`; the root `COPYING` is a plain copy of
it (not a symlink, for portability with tools/archives that don't preserve symlinks). Every
source file (`.py`, `.toml`, `.yml`) carries a 2-line SPDX header
(`SPDX-FileCopyrightText: 2026 Alberto P.` / `SPDX-License-Identifier: MPL-2.0`); files that
can't carry a header comment (`README.md`, `README.it.md`, this file, `.gitignore`, `COPYING`)
are annotated instead via `REUSE.toml`. Check compliance with `pipx run reuse lint` (or
`reuse lint` if the `reuse` tool is already installed) — there's no dedicated CI job for this,
it's a manual check.

## CI

- `.github/workflows/tests.yml` — pytest on the `os × python-version` matrix
  (ubuntu/windows/macos × 3.10–3.13) on every push and PR.
- `.github/workflows/wheels.yml` — builds the wheel once (`build` job, `python -m build --wheel`)
  then, in a separate `test` job, downloads that artifact and runs `pytest` against the
  *installed wheel* across the OS × Python-version matrix (ubuntu-latest/windows-latest ×
  3.10–3.13) — this catches packaging bugs (e.g. a file missing from the wheel) that an editable
  install in `tests.yml` wouldn't. Deliberately does **not** use `pypa/cibuildwheel`: that tool
  is for producing platform-specific (compiled-extension) wheels and, as of newer releases,
  actively refuses to build a pure-Python wheel like this package's (see
  [pypa/cibuildwheel#255](https://github.com/pypa/cibuildwheel/issues/255)) — don't reintroduce
  it here without a real compiled-extension use case.
- `.github/workflows/pypi.yml` — on any `v*` tag push, builds the sdist+wheel (`build` job) then
  publishes them to PyPI (`publish` job) via `pypa/gh-action-pypi-publish` using Trusted
  Publishing (OIDC, `id-token: write`, no stored API token). The `publish` job runs under the
  GitHub Environment named `pypi`, which must be created in the repo settings and registered as
  a trusted publisher on the PyPI project page — this is manual, one-time setup outside the repo,
  not something the workflow file itself can do. PyPI project name is `pdfredactcli` (distinct
  from the importable package/console-script name `pdfredact`) — `pyproject.toml`'s `[project]
  name` and `__init__.py`'s `importlib.metadata.version("pdfredactcli")` lookup must stay in sync
  with this if either ever changes.
- `.github/dependabot.yml` — weekly updates for the `pip` and `github-actions` ecosystems.
