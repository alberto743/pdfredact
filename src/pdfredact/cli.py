# SPDX-FileCopyrightText: 2026 Alberto P.
# SPDX-License-Identifier: MPL-2.0
"""
Interfaccia a riga di comando per pdfredact.

Uso:
    pdfredact input.pdf output.pdf -t "Mario Rossi" -t "CF: ABCDEF"
    pdfredact input.pdf output.pdf -r "\\bMCNP-\\d{4}\\b"
    pdfredact input.pdf output.pdf -t "Confidenziale" --case-sensitive
    pdfredact input.pdf output.pdf -t "foo" --pages 1,2,5-7
    pdfredact input.pdf output.pdf --box "1:56,700,300,730"
    pdfredact input.pdf output.pdf -t "foo" --fill-color "#ff0000"

Coordinate rettangolo (--box):
    Formato: "PAGINA:x0,y0,x1,y1"
    - PAGINA è 1-based (pagina 1 = prima pagina)
    - x0,y0,x1,y1 in punti PDF (72 pt = 1 pollice), origine in alto a sinistra
      (stesso sistema restituito da page.search_for())
    - L'ordine degli angoli è irrilevante: il rettangolo viene normalizzato.

Codici di uscita:
    0 = completato   2 = errore di input/utilizzo
"""

from __future__ import annotations

import argparse
import os
import sys

from .core import fail, parse_box_spec, parse_fill_color, redact_pdf


def main() -> None:
    ap = argparse.ArgumentParser(description="Oscura testo specifico in un PDF con PyMuPDF.")
    ap.add_argument("input", help="PDF di input")
    ap.add_argument("output", help="PDF di output (redatto)")
    ap.add_argument("-t", "--text", action="append", default=[], dest="terms",
                    help="Testo letterale da oscurare (ripetibile)")
    ap.add_argument("-r", "--regex", action="append", default=[], dest="regexes",
                    help="Pattern regex da oscurare (ripetibile)")
    ap.add_argument("--box", action="append", default=[], dest="boxes",
                    metavar="PAGINA:x0,y0,x1,y1",
                    help="Rettangolo esplicito da oscurare, es. '1:56,700,300,730' (ripetibile)")
    ap.add_argument("--case-sensitive", action="store_true",
                    help="Ricerca sensibile a maiuscole/minuscole (default: insensibile)")
    ap.add_argument("--pages", dest="pages", default=None,
                    help="Pagine per la ricerca testuale (-t/-r), es. '1,2,5-7' "
                         "(default: tutte; non influenza --box)")
    ap.add_argument("--fill-color", dest="fill_color", default="#000000",
                    metavar="#RRGGBB",
                    help="Colore di riempimento delle aree oscurate (default: '#000000')")
    args = ap.parse_args()

    if not args.terms and not args.regexes and not args.boxes:
        ap.error("specificare almeno un termine (-t/--text), un pattern (-r/--regex) "
                 "o un rettangolo (--box)")

    # Validazione input/output prima di qualsiasi elaborazione
    if not os.path.isfile(args.input):
        fail(f"file di input non trovato: '{args.input}'")
    if os.path.exists(args.output) and os.path.samefile(args.input, args.output):
        fail("input e output coincidono: la redazione in-place distruggerebbe "
             "l'originale — specificare un file di output diverso")
    out_dir = os.path.dirname(os.path.abspath(args.output))
    if not os.path.isdir(out_dir):
        fail(f"directory di output inesistente: '{out_dir}'")
    if any(not t.strip() for t in args.terms):
        fail("-t/--text non può essere una stringa vuota")

    parsed_boxes = [parse_box_spec(b) for b in args.boxes]
    fill_color = parse_fill_color(args.fill_color)

    hits = redact_pdf(
        args.input, args.output, args.terms, args.regexes, parsed_boxes,
        args.case_sensitive, args.pages, fill_color,
    )

    print(f"Occorrenze oscurate (rettangoli univoci): {hits}")
    print(f"File salvato in: {args.output}")

    if hits == 0:
        print("ATTENZIONE: nessuna occorrenza trovata — il file di output è una copia "
              "non redatta. Verificare il testo cercato: potrebbe essere spezzato su "
              "più righe, usare font/encoding non estraibili, o essere solo immagine "
              "(PDF scansionato, che richiede OCR).", file=sys.stderr)

    print("Nota: NON vengono trattati i metadati del documento (Autore, Titolo, XMP) "
          "né il contenuto di annotazioni/commenti, che non compaiono in get_text(). "
          "Verificare l'output con 'pdftotext' e 'pdfinfo -meta' prima della "
          "distribuzione.", file=sys.stderr)


if __name__ == "__main__":
    main()
