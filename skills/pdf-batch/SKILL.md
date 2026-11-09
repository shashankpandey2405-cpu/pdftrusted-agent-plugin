---
name: pdf-batch
description: Run one PDFTrusted tool over many files or a whole folder — compress every PDF, convert a folder of PDFs to Word or Excel, OCR all scans, add page numbers or a watermark to each file, convert all images or office files to PDF, or merge a folder into one PDF in a chosen order. Use when the user mentions several files, a folder, "all my PDFs", or a recurring job.
---

# Batch work over files (PDFTrusted API)

Client: `python <base>/../../scripts/pdftrusted.py` (setup and limits: the `pdf-tools` skill).

## Steps

1. **List the files first** and show the user what will be processed (count, total size). Skip files that are not
   the right type for the tool. Ask before running more than ~20 files, and tell them each file is one job (guest
   and free plans have a daily limit; `pdftrusted.py usage` shows what is left).
2. **One tool, one file at a time**, in a simple loop — the client handles upload, waiting and download:
   ```
   for each file:  pdftrusted.py run <tool> "<file>" -o "<output folder>" [--opt key=value ...]
   ```
   Write results to a separate output folder (e.g. `<folder>/pdftrusted-out/`) so originals are never touched.
   **Merge** is the exception: one call with all files in the user's order —
   `pdftrusted.py run merge a.pdf b.pdf c.pdf -o merged.pdf`.
3. **Keep going on errors.** Record each failure (file name + `error.code`) and continue; stop the whole batch only
   on `quota_exceeded`, `api_credits_exceeded` or `network`, and tell the user why.
4. **Report a short table**: file → output → size before/after (or pages), plus the failures and what to do about
   them (e.g. `pdf_password`: needs the password; `no_text_layer`: needs OCR first).

## Good batch recipes

- Smaller PDFs for email: `compress` → compare sizes, keep the original if the result is not smaller.
- Searchable archive: `ocr` on scans, then optionally `pdf2pdfa` for long-term storage.
- Office → PDF: `docx2pdf`, `xlsx2pdf`, `pptx2pdf`, `img2pdf` by extension.
- Bank statements: use the `bank-statement-to-excel` skill per file — each one may need the user's review.
