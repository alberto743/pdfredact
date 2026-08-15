# pdfredact

*[Read this in English](README.md)*

Oscura (redazione vera, non solo visiva) di testo in un PDF, usando
[PyMuPDF](https://pymupdf.readthedocs.io/). Individua le occorrenze del testo/pattern
specificato, applica un'annotazione di redazione e la "brucia" nel contenuto della pagina,
rimuovendo fisicamente il testo sottostante (non recuperabile con copia/incolla o estrazione
testo).

## Installazione

Richiede Python 3.9 o superiore. Le dipendenze sono PyMuPDF e PyYAML (per `--config`),
entrambe pubblicano wheel precompilati per Linux, Windows e macOS (nessun compilatore
richiesto).

Il pacchetto è pubblicato su PyPI come [`pdfredactcli`](https://pypi.org/project/pdfredactcli/)
(il comando installato è `pdfredact`).

### Con pip

```sh
pip install pdfredactcli
```

oppure, da un clone locale del repository:

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
pipx install pdfredactcli
```

Oppure, da un clone locale del repository, sostituire l'ultima riga con `pipx install .`
(eseguito dalla radice del repository).

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

Poi, in un nuovo terminale (per far effetto a `ensurepath`):

```powershell
pipx install pdfredactcli
```

Oppure, da un clone locale del repository, eseguire `pipx install .` dalla cartella del
repository.

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
pdfredact input.pdf -t "Mario Rossi"              # scrive input_redacted.pdf
pdfredact --config lavoro.yaml
pdfredact input.pdf output.pdf --config regole.yaml -t "termine extra"
```

Il percorso di output è opzionale: se omesso, viene usato di default
`<input>_redacted.pdf` nella stessa cartella del file di input.

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
- Un rettangolo interamente fuori dalla pagina non oscura nulla: viene segnalato su stderr e
  non conteggiato tra le occorrenze oscurate, così una coordinata errata non sembra un successo.

### File di configurazione (`--config`)

Qualsiasi opzione può essere impostata anche in un file YAML invece di essere ridigitata a ogni
esecuzione:

```yaml
# lavoro.yaml
input: input.pdf               # opzionale se fornito come posizionale sulla riga di comando
output: output.pdf             # opzionale; di default <input>_redacted.pdf se omesso ovunque

text:                          # termini letterali da oscurare (come -t ripetuto)
  - "Mario Rossi"
  - "CF: ABCDEF"

regex:                         # pattern regex da oscurare (come -r ripetuto)
  - '\bMCNP-\d{4}\b'

boxes:                         # rettangoli espliciti, stesso formato "PAGINA:x0,y0,x1,y1" di --box
  - "1:56,700,300,730"

case_sensitive: false          # come --case-sensitive
pages: "1,2,5-7"                # come --pages
fill_color: "#000000"           # come --fill-color
```

Tutte le chiavi sono opzionali, e `pdfredact --config lavoro.yaml` da solo è un'invocazione
valida se `input` è impostato nel file. I valori del file di configurazione e della riga di
comando vengono uniti:

- `text`, `regex` e `boxes` dalla riga di comando vengono **aggiunti** alle liste del file di
  configurazione.
- `input`, `output`, `pages`, `fill_color` e `case-sensitive` dalla riga di comando **sovrascrivono**
  il valore del file di configurazione quando specificati esplicitamente. Per riportare a `false`
  un `case_sensitive: true` impostato nel file di configurazione, usare `--no-case-sensitive`
  (il semplice `--case-sensitive` può solo impostarlo a `true`).

Ogni chiave viene validata come il corrispondente parametro CLI (stessi formati di
`--box`/`--pages`/`--fill-color`); una chiave sconosciuta o un valore di tipo/formato errato
termina immediatamente con codice di uscita 2 invece di essere ignorato silenziosamente.

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
