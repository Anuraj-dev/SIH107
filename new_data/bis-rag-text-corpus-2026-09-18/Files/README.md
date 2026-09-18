# BIS PDF-to-text corpus

This folder contains one UTF-8 `.txt` file for each PDF in the source folder:

`/home/raja/bis-prototype-corpus-2026-09-18/files`

The filenames use the same PDF stem, so `example.pdf` maps to `example.txt`.

- 357 digitally readable PDFs use the official English section embedded in the BIS document; duplicate Hindi lines were removed.
- 2 scanned Hindi-only PDFs use Hindi OCR plus English translation. Their files begin with an OCR/translation notice.
- `conversion_manifest.json` records the source PDF, output file, method, character count, and status.

The two scanned translations are suitable for prototype retrieval, but should be human-reviewed before legal, regulatory, or compliance decisions.
