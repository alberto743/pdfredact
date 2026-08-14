# SPDX-FileCopyrightText: 2026 Alberto P.
# SPDX-License-Identifier: MPL-2.0
"""pdfredact — redact text in a PDF (true redaction, not just a visual overlay)."""

from importlib.metadata import PackageNotFoundError, version

from .core import redact_pdf

try:
    __version__ = version("pdfredactcli")
except PackageNotFoundError:  # pragma: no cover - package not installed
    __version__ = "0.0.0"

__all__ = ["redact_pdf", "__version__"]
