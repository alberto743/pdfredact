# SPDX-FileCopyrightText: 2026 Alberto P.
# SPDX-License-Identifier: MPL-2.0
"""pdfredact — oscura (redazione vera, non solo visiva) testo in un PDF."""

from .core import redact_pdf

__version__ = "0.1.0"
__all__ = ["redact_pdf", "__version__"]
