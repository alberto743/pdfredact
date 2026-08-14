# pdfredact

*[Read this in English](README.md)*

Oscura (redazione vera, non solo visiva) di testo in un PDF, usando
[PyMuPDF](https://pymupdf.readthedocs.io/). Individua le occorrenze del testo/pattern
specificato, applica un'annotazione di redazione e la "brucia" nel contenuto della pagina,
rimuovendo fisicamente il testo sottostante (non recuperabile con copia/incolla o estrazione
testo).

## Installazione

Richiede Python 3.10 o superiore. L'unica dipendenza è PyMuPDF, che pubblica wheel
precompilati per Linux, Windows e macOS (nessun compilatore richiesto).

### Con pip

```sh
pip install .
```

oppure, per sviluppo (installazione editabile con le dipendenze di test):

```sh
pip install -e .[test]
```

### Con pipx (consigliato per un tool a riga di comando)

[pipx](https://pipx.pypa.io/stable/) installa il tool in un ambiente virtuale isolato ed
espone solo il comando `pdfredact` nel `PATH`, senza toccare il Python di sistema.

**Linux/macOS:**

```sh
python3 -m pip install --user pipx
python3 -m pipx ensurepath
pipx install .          # eseguito dalla radice del repository
```

**Windows:**

Su Windows conviene installare `pipx` tramite [Scoop](https://scoop.sh/), che gestisce anche
l'aggiornamento di Python stesso se necessario:

```powershell
# Se Scoop non è già installato:
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression

scoop install pipx
pipx ensurepath
```

Poi, dalla cartella del repository (in un nuovo terminale, per far effetto a `ensurepath`):

```powershell
pipx install .
```

In entrambi i casi, dopo l'installazione il comando `pdfredact` è disponibile direttamente in
un nuovo terminale.

## Utilizzo

```sh
pdfredact input.pdf output.pdf -t "Mario Rossi" -t "CF: ABCDEF"
pdfredact input.pdf output.pdf -r "\bMCNP-\d{4}\b"
pdfredact input.pdf output.pdf -t "Confidenziale" --case-sensitive
pdfredact input.pdf output.pdf -t "foo" --pages 1,2,5-7
pdfredact input.pdf output.pdf --box "1:56,700,300,730"
pdfredact input.pdf output.pdf -t "foo" --fill-color "#ff0000"
```

Equivalente senza installazione, dalla radice del repository:

```sh
python -m pdfredact input.pdf output.pdf -t "Mario Rossi"
```

### Coordinate rettangolo (`--box`)

Formato: `PAGINA:x0,y0,x1,y1`

- `PAGINA` è 1-based (pagina 1 = prima pagina)
- `x0,y0,x1,y1` in punti PDF (72 pt = 1 pollice), origine in alto a sinistra (stesso sistema
  restituito da `page.search_for()`)
- L'ordine degli angoli è irrilevante: il rettangolo viene normalizzato.

### Codici di uscita

`0` = completato, `2` = errore di input/utilizzo.

## Limitazioni note

- Non vengono trattati i metadati del documento (Autore, Titolo, XMP) né il contenuto di
  annotazioni/commenti, che non compaiono in `get_text()`.
- Un termine spezzato su più righe nel layout del PDF potrebbe non essere trovato.
- I PDF scansionati (solo immagine, senza testo estraibile) richiedono OCR a monte: lo
  strumento non trova nulla da oscurare in quel caso.

Verificare sempre l'output con `pdftotext` e `pdfinfo -meta` prima della distribuzione.

## Compatibilità Windows

Il progetto è testato in CI su Linux, Windows e macOS (vedi `.github/workflows/tests.yml`) ed
è compatibile con Windows senza modifiche: usa solo `os.path` (nessun separatore hardcoded),
nessuna chiamata POSIX-only, e `os.path.samefile` funziona correttamente su Windows dalla
3.2 di Python.

## Sviluppo

```sh
pip install -e .[test]
pytest
pytest tests/test_core.py::test_redact_pdf_literal_term   # singolo test
```

## Sviluppo assistito da IA

Il codice, i test e la documentazione di questo progetto sono stati sviluppati con
l'assistenza di strumenti di intelligenza artificiale (Claude Code). Ogni modifica è stata
rivista prima della pubblicazione; eventuali problemi riscontrati possono essere segnalati
tramite l'issue tracker del progetto.

## Licenza

[MPL-2.0](COPYING). Il repository è conforme a [REUSE](https://reuse.software/); per
verificare: `pipx run reuse lint`.
