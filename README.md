# PDFTrusted for AI agents

A Claude Code plugin (and Agent Skills) that lets your agent do real work on PDFs through the
[PDFTrusted API](https://developers.pdftrusted.com):

- **pdf-tools** — compress, merge, split, rotate, convert PDF ⇄ Word / Excel / PowerPoint / images, OCR scans,
  protect, unlock, watermark, page numbers, redact, PDF/A, compare and 60+ more.
- **bank-statement-to-excel** — bank and credit-card statements to Excel where every row is checked against the
  statement's own balances. Rows that do not add up are shown with a reason; the agent fixes them **with you**, never
  by guessing, and the Excel says which rows are *verified* and which a person *reviewed*.
- **pdf-batch** — run a tool over a folder: compress everything, OCR every scan, convert a folder to Word, merge in
  your order. Originals are never overwritten.

## Install (Claude Code)

```bash
/plugin marketplace add shashankpandey2405-cpu/pdftrusted-agent-plugin
/plugin install pdftrusted@pdftrusted
```

Get a free API key at https://developers.pdftrusted.com and set it:

```bash
export PDFTRUSTED_API_KEY=sk_...
```

Without a key the client works as a guest (a few jobs a day, 25 MB / 50 pages) — enough to try it. As a guest it keeps one
cookie in `~/.pdftrusted/cookies.txt` (or `PDFTRUSTED_COOKIE_FILE`) so a later command can reach the same task.

## MCP server (Claude Desktop, Cursor, Windsurf, any MCP client)

`scripts/mcp_server.py` is a dependency-free MCP server (stdio) with six tools: `pdf_tools`, `pdf_run`,
`statement_check`, `statement_excel`, `usage`, `delete_task`. The Claude Code plugin starts it for you. For other
clients, add it to their MCP config (`python` instead of `python3` on Windows):

```json
{
  "mcpServers": {
    "pdftrusted": {
      "command": "python3",
      "args": ["/path/to/pdftrusted-agent-plugin/scripts/mcp_server.py"],
      "env": { "PDFTRUSTED_API_KEY": "sk_..." }
    }
  }
}
```

## Use without an agent

The skills drive one dependency-free client (Python 3.8+), which also works on its own:

```bash
python scripts/pdftrusted.py tools --query excel
python scripts/pdftrusted.py run compress report.pdf -o out/
python scripts/pdftrusted.py run merge a.pdf b.pdf c.pdf -o merged.pdf
python scripts/pdftrusted.py statement statement.pdf                    # check every row
python scripts/pdftrusted.py statement statement.pdf --xlsx --review-of <task_id> [--review review.json]
python scripts/pdftrusted.py usage
```

Every command prints one JSON object; errors are `{"error": {"code", "message"}}` with exit code 2.

## Pricing

API jobs spend credits from the [published price list](https://developers.pdftrusted.com/pricing) (e.g. PDF to Word
1 credit per page, compress 4 per file, bank statement 2 per page with a minimum of 4 — the reviewed Excel of a
statement you just read is free). Website and guest jobs use the daily job allowance instead.

## Privacy

Files go to PDFTrusted only for the job and are deleted within an hour (`pdftrusted.py delete <task_id>` deletes them
at once). The client never prints file contents and never stores passwords.

## Development

```bash
python -m unittest discover -s tests
```

MIT licensed.
