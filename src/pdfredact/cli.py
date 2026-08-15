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

from .core import fail, parse_box_spec, parse_fill_color, redact_pdf


def main() -> None:
    ap = argparse.ArgumentParser(description="Redact specific text in a PDF using PyMuPDF.")
    ap.add_argument("input", help="Input PDF")
    ap.add_argument("output", nargs="?", default=None,
                    help="Output (redacted) PDF (default: '<input>_redacted.pdf')")
    ap.add_argument("-t", "--text", action="append", default=[], dest="terms",
                    help="Literal text to redact (repeatable)")
    ap.add_argument("-r", "--regex", action="append", default=[], dest="regexes",
                    help="Regex pattern to redact (repeatable)")
    ap.add_argument("--box", action="append", default=[], dest="boxes",
                    metavar="PAGE:x0,y0,x1,y1",
                    help="Explicit rectangle to redact, e.g. '1:56,700,300,730' (repeatable)")
    ap.add_argument("--case-sensitive", action="store_true",
                    help="Case-sensitive search (default: case-insensitive)")
    ap.add_argument("--pages", dest="pages", default=None,
                    help="Pages for text search (-t/-r), e.g. '1,2,5-7' "
                         "(default: all; does not affect --box)")
    ap.add_argument("--fill-color", dest="fill_color", default="#000000",
                    metavar="#RRGGBB",
                    help="Fill color for redacted areas (default: '#000000')")
    args = ap.parse_args()

    if not args.terms and not args.regexes and not args.boxes:
        ap.error("specify at least one term (-t/--text), one pattern (-r/--regex) "
                 "or one rectangle (--box)")

    # Validate input/output before any processing
    if not os.path.isfile(args.input):
        fail(f"input file not found: '{args.input}'")
    if args.output is None:
        root, _ext = os.path.splitext(args.input)
        args.output = f"{root}_redacted.pdf"
    if os.path.exists(args.output) and os.path.samefile(args.input, args.output):
        fail("input and output are the same file: in-place redaction would "
             "destroy the original - specify a different output file")
    out_dir = os.path.dirname(os.path.abspath(args.output))
    if not os.path.isdir(out_dir):
        fail(f"output directory does not exist: '{out_dir}'")
    if any(not t.strip() for t in args.terms):
        fail("-t/--text cannot be an empty string")
    if any(not r.strip() for r in args.regexes):
        fail("-r/--regex cannot be an empty string")

    parsed_boxes = [parse_box_spec(b) for b in args.boxes]
    fill_color = parse_fill_color(args.fill_color)

    hits = redact_pdf(
        args.input, args.output, args.terms, args.regexes, parsed_boxes,
        args.case_sensitive, args.pages, fill_color,
    )

    print(f"Occurrences redacted (unique rectangles): {hits}")
    print(f"File saved to: {args.output}")

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
