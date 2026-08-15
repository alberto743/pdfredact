# SPDX-FileCopyrightText: 2026 Alberto P.
# SPDX-License-Identifier: MPL-2.0
"""
Command-line interface for pdfredact.

Usage:
    pdfredact input.pdf output.pdf -t "Mario Rossi" -t "CF: ABCDEF"
    pdfredact input.pdf output.pdf -r "\\bMCNP-\\d{4}\\b"
    pdfredact input.pdf output.pdf -t "Confidential" --case-sensitive
    pdfredact input.pdf output.pdf -t "foo" --pages 1,2,5-7
    pdfredact input.pdf output.pdf --box "1:56,700,300,730"
    pdfredact input.pdf output.pdf -t "foo" --fill-color "#ff0000"
    pdfredact input.pdf -t "Mario Rossi"   # writes input_redacted.pdf
    pdfredact --config job.yaml
    pdfredact input.pdf output.pdf --config rules.yaml -t "extra one-off term"

Box coordinates (--box):
    Format: "PAGE:x0,y0,x1,y1"
    - PAGE is 1-based (page 1 = first page)
    - x0,y0,x1,y1 in PDF points (72 pt = 1 inch), origin at the top-left
      (same coordinate system returned by page.search_for())
    - Corner order doesn't matter: the rectangle is normalized.

Exit codes:
    0 = success   2 = input/usage error
"""

from __future__ import annotations

import argparse
import os
import sys

from .core import (
    DEFAULT_FILL_COLOR, fail, load_config, parse_box_spec, parse_fill_color, redact_pdf,
)


def main() -> None:
    ap = argparse.ArgumentParser(description="Redact specific text in a PDF using PyMuPDF.")
    ap.add_argument("input", nargs="?", default=None,
                    help="Input PDF (optional if 'input:' is set in --config)")
    ap.add_argument("output", nargs="?", default=None,
                    help="Output (redacted) PDF (default: '<input>_redacted.pdf')")
    ap.add_argument("-c", "--config", dest="config", default=None, metavar="FILE.yaml",
                    help="YAML file with redaction options, merged with other flags "
                         "(see README)")
    ap.add_argument("-t", "--text", action="append", default=[], dest="terms",
                    help="Literal text to redact (repeatable)")
    ap.add_argument("-r", "--regex", action="append", default=[], dest="regexes",
                    help="Regex pattern to redact (repeatable)")
    ap.add_argument("--box", action="append", default=[], dest="boxes",
                    metavar="PAGE:x0,y0,x1,y1",
                    help="Explicit rectangle to redact, e.g. '1:56,700,300,730' (repeatable)")
    ap.add_argument("--case-sensitive", action=argparse.BooleanOptionalAction, default=None,
                    help="Case-sensitive search (default: case-insensitive). Use "
                         "--no-case-sensitive to override a config file's "
                         "'case_sensitive: true' back to false")
    ap.add_argument("--pages", dest="pages", default=None,
                    help="Pages for text search (-t/-r), e.g. '1,2,5-7' "
                         "(default: all; does not affect --box)")
    ap.add_argument("--fill-color", dest="fill_color", default=None,
                    metavar="#RRGGBB",
                    help=f"Fill color for redacted areas (default: '{DEFAULT_FILL_COLOR}')")
    args = ap.parse_args()

    config = load_config(args.config) if args.config else {}

    # Merge: CLI list flags add to the config's lists; CLI scalar flags
    # override the config's value when explicitly passed.
    input_path = args.input or config.get("input")
    if not input_path:
        ap.error("input PDF is required (positional argument or 'input:' in --config)")
    output_path = args.output or config.get("output")
    terms = args.terms + config.get("text", [])
    regexes = args.regexes + config.get("regex", [])
    box_specs = args.boxes + config.get("boxes", [])
    case_sensitive = (
        args.case_sensitive if args.case_sensitive is not None
        else config.get("case_sensitive", False)
    )
    pages = args.pages if args.pages is not None else config.get("pages")
    fill_color_spec = (
        args.fill_color if args.fill_color is not None
        else config.get("fill_color", DEFAULT_FILL_COLOR)
    )

    if not terms and not regexes and not box_specs:
        ap.error("specify at least one term (-t/--text), one pattern (-r/--regex) "
                 "or one rectangle (--box), on the command line or in --config")

    # Validate input/output before any processing
    if not os.path.isfile(input_path):
        fail(f"input file not found: '{input_path}'")
    if output_path is None:
        root, _ext = os.path.splitext(input_path)
        output_path = f"{root}_redacted.pdf"
    if os.path.exists(output_path) and os.path.samefile(input_path, output_path):
        fail("input and output are the same file: in-place redaction would "
             "destroy the original - specify a different output file")
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if not os.path.isdir(out_dir):
        fail(f"output directory does not exist: '{out_dir}'")
    if any(not t.strip() for t in terms):
        fail("-t/--text cannot be an empty string")
    if any(not r.strip() for r in regexes):
        fail("-r/--regex cannot be an empty string")

    parsed_boxes = [parse_box_spec(b) for b in box_specs]
    fill_color = parse_fill_color(fill_color_spec)

    hits = redact_pdf(
        input_path, output_path, terms, regexes, parsed_boxes,
        case_sensitive, pages, fill_color,
    )

    print(f"Occurrences redacted (unique rectangles): {hits}")
    print(f"File saved to: {output_path}")

    if hits == 0:
        print("WARNING: no occurrences found - the output file is an unredacted "
              "copy. Check the searched text: it might be split across multiple "
              "lines, use a non-extractable font/encoding, or be image-only "
              "(a scanned PDF, which requires OCR).", file=sys.stderr)

    print("Note: document metadata (Author, Title, XMP) and annotation/comment "
          "content are NOT handled, since they don't appear in get_text(). "
          "Verify the output with 'pdftotext' and 'pdfinfo -meta' before "
          "distribution.", file=sys.stderr)


if __name__ == "__main__":
    main()
