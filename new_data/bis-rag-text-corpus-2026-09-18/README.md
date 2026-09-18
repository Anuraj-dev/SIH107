# BIS RAG text corpus

This is the clean teammate-ready corpus. It contains no PDFs.

## Contents

- `Files/` — 359 UTF-8 `.txt` files, one for every PDF in the source corpus. Filenames preserve the original PDF stem.
- `data/standards_metadata.ndjson` — BIS standard catalogue metadata.
- `data/standard_documents.ndjson` — BIS document/attachment metadata and provenance.
- `data/files.ndjson` — original public attachment references.
- `conversion_manifest.json` — conversion method and status for every TXT file.
- `bis_corpus_manifest.json` — original BIS crawl manifest and source API information.

The TXT files are extracted text, not the original PDFs. For bilingual BIS documents, the official English section was retained and duplicate Hindi lines were removed. Two scanned Hindi-only documents were OCR-assisted and translated to English; those entries are marked in `conversion_manifest.json` and should be reviewed before legal or compliance use.

This structure is suitable for chunking, embedding, and RAG ingestion. Use the metadata files to attach standard number, department, committee, publication date, and source provenance to each document.
