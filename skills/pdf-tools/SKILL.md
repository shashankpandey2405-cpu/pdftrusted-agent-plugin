---
name: pdf-tools
description: Do real work on PDF and office files through the PDFTrusted API — compress, merge, split, rotate, convert PDF to Word/Excel/PowerPoint/images and back, OCR scanned PDFs, protect or unlock, watermark, page numbers, redact, PDF/A, compare and 60+ more. Use when the user asks to change, convert, shrink, combine, split, secure or make searchable a PDF or office file on disk, or asks which PDF operations are possible.
---

# PDF tools (PDFTrusted API)

All work goes through one client that ships with this plugin:

```
python <plugin root>/scripts/pdftrusted.py <command> ...
```

`<plugin root>` is two folders up from this skill's base directory (`<base>/../../scripts/pdftrusted.py`).
Every command prints one JSON object. An error looks like `{"error": {"code", "message"}}` (exit code 2) — read the
message, it says what to do.

## Steps

1. **Find the tool.** If you are not sure of the tool id or its options, run
   `pdftrusted.py tools --query <word>` (e.g. `excel`, `word`, `compress`, `ocr`, `merge`). Use the `tool` value it
   returns. Common ids: `compress`, `merge`, `split`, `rotate`, `pdf2docx`, `pdf2xlsx`, `pdf2pptx`, `pdf2img`,
   `docx2pdf`, `xlsx2pdf`, `pptx2pdf`, `img2pdf`, `ocr`, `protect`, `unlock`, `watermark`, `page-numbers`, `redact`,
   `pdf2pdfa`, `compare-pdf`, `extract-text`, `pdf-to-markdown`.
2. **Run it.** `pdftrusted.py run <tool> <file> [<file> ...] [-o <output path or folder>] [--opt key=value ...]`
   - Several inputs (merge, img2pdf, compare-pdf) are uploaded in the order given.
   - Options take JSON values: `--opt pages="1-3"`, `--opt angle=90`, `--opt password="..."`.
   - The output is written next to the first input unless `-o` is given; an input file is never overwritten.
3. **Report** the output path and size to the user. Do not paste file contents back.

## Rules

- Ask before overwriting or deleting the user's files; the client never does either by itself.
- A password the user gives you goes only into `--opt password=...` for that one call. Never write it to a file or
  repeat it back.
- Results stay on the server for about an hour. If the user wants the server copy gone now:
  `pdftrusted.py delete <task_id>`.
- Limits: without `PDFTRUSTED_API_KEY` the client runs as a guest (a few jobs a day, 25 MB / 50 pages). When the
  error code is `quota_exceeded` or `api_credits_exceeded`, tell the user and point them to
  https://developers.pdftrusted.com for a key — do not retry in a loop.
- `pdftrusted.py usage` shows what is left today.

## Choosing well

- "Make it smaller for email / WhatsApp" → `compress`.
- "Make this scan searchable / copy text from a scan" → `ocr` (then `extract-text` if they want plain text).
- "Edit this PDF in Word" → `pdf2docx`. "Tables into Excel" → `pdf2xlsx`. A **bank or card statement** into Excel →
  use the `bank-statement-to-excel` skill instead: it checks every row against the balances.
- Many files at once → the `pdf-batch` skill.
