# SPDX-FileCopyrightText: 2026 Alberto P.
# SPDX-License-Identifier: MPL-2.0
"""
Logica di redazione PDF (oscuramento reale, non solo visivo).

Usa PyMuPDF: individua le occorrenze del testo/pattern specificato, applica
un'annotazione di redazione e la "brucia" nel contenuto della pagina con
apply_redactions(), rimuovendo fisicamente il testo sottostante (non
recuperabile con copia/incolla o estrazione testo).
"""

from __future__ import annotations

import re
import sys
from typing import NoReturn

# L'alias `fitz` è deprecato e stampa un warning su stdout, inquinando l'output
# in pipeline; si preferisce il nome canonico quando disponibile.
try:
    import pymupdf as fitz
except ImportError:  # PyMuPDF < 1.24
    import fitz


def fail(message: str) -> NoReturn:
    """Termina con errore di input/utilizzo (exit code 2)."""
    print(f"Errore: {message}", file=sys.stderr)
    sys.exit(2)


def parse_page_ranges(spec: str, n_pages: int) -> set[int]:
    """
    Converte '1,2,5-7' in un set di indici 0-based.

    Valida esplicitamente ogni token: numeri non interi, pagine <= 0 e intervalli
    invertiti generano un errore, invece di propagare un ValueError grezzo o di
    produrre silenziosamente un set vuoto (che porterebbe a un PDF non redatto).
    """
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part.lstrip("-"):
                a_str, b_str = part.split("-", 1)
                a, b = int(a_str), int(b_str)
                if a < 1 or b < 1:
                    raise ValueError
                if a > b:
                    fail(f"intervallo di pagine invertito in --pages: '{part}' "
                         f"(atteso 'minore-maggiore', es. '5-7')")
                pages.update(range(a - 1, b))
            else:
                n = int(part)
                if n < 1:
                    raise ValueError
                pages.add(n - 1)
        except ValueError:
            fail(f"valore non valido in --pages: '{part}' "
                 f"(attesi numeri di pagina interi >= 1, es. '1,2,5-7')")

    valid = {p for p in pages if 0 <= p < n_pages}
    out_of_range = sorted(p + 1 for p in pages - valid)
    if out_of_range:
        print(f"Attenzione: pagine fuori range ignorate (il documento ha "
              f"{n_pages} pagine): {out_of_range}", file=sys.stderr)
    if not valid:
        fail(f"--pages non seleziona alcuna pagina valida (documento di {n_pages} pagine)")
    return valid


def parse_box_spec(spec: str) -> tuple[int, "fitz.Rect"]:
    """
    Converte 'PAGINA:x0,y0,x1,y1' in (indice_pagina_0based, fitz.Rect).

    Normalizza il rettangolo: un box con gli angoli in ordine inverso
    (es. x1 < x0) risulterebbe altrimenti "vuoto" per PyMuPDF e verrebbe
    ignorato senza errori, producendo un PDF non redatto pur riportando
    l'occorrenza come oscurata.
    """
    if ":" not in spec:
        fail(f"formato --box non valido: '{spec}' (atteso 'PAGINA:x0,y0,x1,y1')")

    page_part, coords_part = spec.split(":", 1)
    try:
        page_no = int(page_part.strip()) - 1
    except ValueError:
        fail(f"numero di pagina non valido in --box: '{page_part}' (atteso un intero >= 1)")
    if page_no < 0:
        fail(f"numero di pagina non valido in --box: '{page_part}' (le pagine partono da 1)")

    coords = [c.strip() for c in coords_part.split(",")]
    if len(coords) != 4:
        fail(f"formato --box non valido: '{spec}' — attese 4 coordinate "
             f"(x0,y0,x1,y1), ricevute {len(coords)}")
    try:
        values = [float(c) for c in coords]
    except ValueError:
        fail(f"coordinate non numeriche in --box: '{coords_part}'")

    # normalize() muta il rettangolo in-place; non riassegnare il risultato
    # (a seconda della versione di PyMuPDF può restituire None invece di self,
    # il che trasformerebbe `rect` in None e farebbe fallire `rect.is_empty`
    # più sotto con un AttributeError anziché il fail() previsto).
    rect = fitz.Rect(*values)
    rect.normalize()
    if rect.is_empty:
        fail(f"--box degenere (area nulla): '{spec}' — x0 e x1 (o y0 e y1) coincidono")
    return page_no, rect


def parse_fill_color(spec: str) -> tuple[float, float, float]:
    """Converte '#RRGGBB' in una tupla RGB con componenti in [0, 1]."""
    value = spec.strip().lstrip("#")
    if len(value) != 6:
        fail(f"--fill-color non valido: '{spec}' (atteso formato esadecimale '#RRGGBB')")
    try:
        r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        fail(f"--fill-color non valido: '{spec}' (atteso formato esadecimale '#RRGGBB')")
    return r / 255, g / 255, b / 255


def find_rects_for_pattern(
    page: "fitz.Page", pattern: "re.Pattern", case_sensitive: bool
) -> list["fitz.Rect"]:
    """
    Trova i rettangoli corrispondenti a un pattern regex compilato su una pagina.

    Deduplica le stringhe matchate prima di interrogare search_for() (che restituisce
    TUTTE le occorrenze di quella stringa nella pagina), evitando la moltiplicazione
    dei rettangoli quando lo stesso testo compare più volte. Se case_sensitive=True,
    filtra i rettangoli verificando il testo effettivo al loro interno, perché
    search_for() è internamente case-insensitive.
    """
    text = page.get_text()
    # I match vuoti (es. regex 'X*' o '.?' che possono matchare stringa nulla)
    # farebbero restituire None a search_for(), causando un TypeError.
    unique_strings = dict.fromkeys(
        m.group(0) for m in pattern.finditer(text) if m.group(0).strip()
    )

    rects = []
    for s in unique_strings:
        found = page.search_for(s)
        if not found:  # None o lista vuota
            continue
        for r in found:
            if case_sensitive and page.get_textbox(r).strip() != s.strip():
                continue
            rects.append(r)
    return rects


def dedupe_rects(rects: list["fitz.Rect"], precision: int = 2) -> list["fitz.Rect"]:
    """Rimuove rettangoli duplicati/coincidenti (stesse coordinate arrotondate)."""
    seen = set()
    unique = []
    for r in rects:
        key = tuple(round(v, precision) for v in (r.x0, r.y0, r.x1, r.y1))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def redact_pdf(
    input_path: str,
    output_path: str,
    terms: list[str],
    regexes: list[str],
    boxes: list[tuple[int, "fitz.Rect"]],
    case_sensitive: bool,
    page_spec: str | None,
    fill_color: tuple[float, float, float] = (0, 0, 0),
) -> int:
    try:
        doc = fitz.open(input_path)
    except Exception as exc:
        fail(f"impossibile aprire '{input_path}': {exc}")

    try:
        # Un PDF cifrato si apre ma le pagine non sono accessibili: senza questo
        # controllo il fallimento emerge più avanti come traceback oscuro.
        if doc.needs_pass:
            fail(f"'{input_path}' è protetto da password: decifrarlo prima "
                 f"(es. 'qpdf --password=PW --decrypt in.pdf out.pdf')")
        if doc.page_count == 0:
            fail(f"'{input_path}' non contiene pagine")

        target_pages = (
            parse_page_ranges(page_spec, doc.page_count)
            if page_spec else set(range(doc.page_count))
        )

        # I box specificano già la propria pagina, quindi non sono filtrati da --pages
        boxes_by_page: dict[int, list] = {}
        for pno, rect in boxes:
            if pno >= doc.page_count:
                print(f"Attenzione: --box su pagina {pno + 1} ignorato "
                      f"(il documento ha {doc.page_count} pagine).", file=sys.stderr)
                continue
            boxes_by_page.setdefault(pno, []).append(rect)

        # Un termine letterale è una regex con caratteri speciali escapati:
        # unifica la pipeline di ricerca e garantisce che --case-sensitive
        # funzioni in entrambi i casi.
        flags = 0 if case_sensitive else re.IGNORECASE
        compiled_patterns = [re.compile(re.escape(t), flags) for t in terms]
        for rx in regexes:
            try:
                compiled_patterns.append(re.compile(rx, flags))
            except re.error as exc:
                fail(f"regex non valida '{rx}': {exc}")

        total_hits = 0
        for pno in sorted(target_pages | set(boxes_by_page)):
            page = doc[pno]
            rects = []

            if pno in target_pages:
                for pattern in compiled_patterns:
                    rects.extend(find_rects_for_pattern(page, pattern, case_sensitive))

            rects.extend(boxes_by_page.get(pno, []))
            rects = dedupe_rects(rects)
            if not rects:
                continue

            for r in rects:
                page.add_redact_annot(r, fill=fill_color)
            # PDF_REDACT_IMAGE_PIXELS azzera anche i pixel delle immagini coperte
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
            total_hits += len(rects)

        try:
            # garbage=4 rimuove oggetti orfani non referenziati (stream, font).
            # NON rimuove i metadati del documento: vedi avviso in main().
            doc.save(output_path, garbage=4, deflate=True, clean=True)
        except Exception as exc:
            fail(f"impossibile scrivere '{output_path}': {exc}")

        return total_hits
    finally:
        doc.close()
