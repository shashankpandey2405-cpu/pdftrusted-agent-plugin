#!/usr/bin/env python3
"""PDFTrusted MCP server (stdio, standard library only).

Gives any MCP client (Claude Desktop, Claude Code, Cursor, Windsurf, ...) the PDFTrusted tools: search the tool list,
run a tool on local files, read a bank statement with every row checked against its balances, export the reviewed
Excel, show usage and delete a task's server copy. It drives the same client as the CLI (pdftrusted.py), so auth
(PDFTRUSTED_API_KEY, else a guest cookie), limits and file handling are identical: a result is written next to its
input (never over it) unless `output` says where.

Protocol: JSON-RPC 2.0, one message per line on stdin/stdout. Logs go to stderr only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import traceback
from pathlib import Path

_spec = importlib.util.spec_from_file_location("pdftrusted", Path(__file__).with_name("pdftrusted.py"))
pt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pt)

PROTOCOL = "2025-06-18"
SERVER = {"name": "pdftrusted", "version": pt.VERSION}
INSTRUCTIONS = (
    "PDFTrusted runs PDF jobs on files the user names. Use pdf_tools to find a tool and its options, pdf_run to run it. "
    "For bank or card statements use statement_check first: a row is VERIFIED only when the statement's own balances "
    "prove it. Show the user the needs_check rows and ask for corrections or approvals; never invent a correction. "
    "Then call statement_excel with review_of (free within an hour for the same file). A person's approval makes a row "
    "REVIEWED, never VERIFIED. Offer delete_task when the user is done with a personal document."
)


def _ns(**kw) -> argparse.Namespace:
    return argparse.Namespace(**kw)


def _files(v) -> list[str]:
    if isinstance(v, str):
        return [v]
    if not isinstance(v, list) or not v or not all(isinstance(x, str) for x in v):
        raise pt.ApiError("bad_request", "files must be a path or a list of paths")
    return v


def t_tools(args: dict) -> dict:
    return pt.cmd_tools(_ns(query=args.get("query")))


def t_run(args: dict) -> dict:
    opts = args.get("options") or {}
    if not isinstance(opts, dict):
        raise pt.ApiError("bad_request", "options must be an object")
    pairs = [f"{k}={json.dumps(v)}" for k, v in opts.items()]
    return pt.cmd_run(_ns(tool=args["tool"], files=_files(args["files"]), out=args.get("output"), opt=pairs))


def t_statement_check(args: dict) -> dict:
    return pt.cmd_statement(_ns(file=args["file"], xlsx=False, review=None, review_of=None, out=None,
                                limit=int(args.get("limit") or 50)))


def t_statement_excel(args: dict) -> dict:
    review = args.get("review")
    if review is not None and not isinstance(review, dict):
        raise pt.ApiError("bad_request", "review must be an object: {by, corrections: [...], approve: [...]}")
    return pt.cmd_statement(_ns(file=args["file"], xlsx=True, review=None,
                                review_json=json.dumps(review) if review else None,
                                review_of=args.get("review_of"), out=args.get("output"), limit=50))


def t_usage(_args: dict) -> dict:
    return pt.cmd_usage(None)


def t_delete(args: dict) -> dict:
    return pt.cmd_delete(_ns(task_id=args["task_id"]))


_PATHS = {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}, "minItems": 1}]}
TOOLS = [
    {"name": "pdf_tools", "fn": t_tools,
     "description": "List PDFTrusted tools (compress, merge, split, rotate, PDF to Word/Excel/PowerPoint/images, OCR, "
                    "protect, unlock, watermark, redact, page numbers, PDF/A, compare and more) with their credit cost "
                    "and options. Filter with a word such as 'excel', 'word', 'ocr' or 'compress'.",
     "annotations": {"readOnlyHint": True, "openWorldHint": True},
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "word to filter by"}}}},
    {"name": "pdf_run", "fn": t_run,
     "description": "Run one PDFTrusted tool on local files and save the result. Merge takes several files in order; most "
                    "tools take one. The input is never overwritten: the result goes next to it (e.g. "
                    "report-compress.pdf) or to `output`.",
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
     "inputSchema": {"type": "object", "required": ["tool", "files"], "properties": {
         "tool": {"type": "string", "description": "tool id from pdf_tools, e.g. compress, merge, pdf2docx, ocr"},
         "files": {**_PATHS, "description": "absolute path, or a list of paths in order"},
         "options": {"type": "object", "description": "tool options from pdf_tools, e.g. {\"angle\": 90}"},
         "output": {"type": "string", "description": "output file or folder (optional)"}}}},
    {"name": "statement_check", "fn": t_statement_check,
     "description": "Read a bank or credit-card statement PDF and check every transaction against the balances printed "
                    "on it. Returns state (VERIFIED / NEEDS_REVIEW / FAILED), reason codes, row counts, the rows that "
                    "need a check (row, date, description, amounts, page, reasons) and the task_id for statement_excel.",
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
     "inputSchema": {"type": "object", "required": ["file"], "properties": {
         "file": {"type": "string", "description": "path to the statement PDF (unlock it first with pdf_run unlock)"},
         "limit": {"type": "integer", "description": "max rows in needs_check (default 50)"}}}},
    {"name": "statement_excel", "fn": t_statement_excel,
     "description": "Download the statement as Excel with a Check column, Summary, Sources and (after a review) a "
                    "Review log. Pass review_of = the task_id from statement_check (free within an hour for the same "
                    "file) and the user's review: {\"by\": name, \"corrections\": [{\"row\": 2, \"field\": \"debit\", "
                    "\"value\": \"450.38\"}], \"approve\": [5]}. Only use values the user gave.",
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
     "inputSchema": {"type": "object", "required": ["file"], "properties": {
         "file": {"type": "string"}, "review_of": {"type": "string"},
         "review": {"type": "object", "properties": {
             "by": {"type": "string"},
             "corrections": {"type": "array", "items": {"type": "object", "required": ["row", "field", "value"],
                                                        "properties": {
                 "row": {"type": "integer"},
                 "field": {"enum": ["date", "description", "debit", "credit", "balance"]},
                 "value": {"type": "string"}}}},
             "approve": {"type": "array", "items": {"type": "integer"}}}},
         "output": {"type": "string"}}}},
    {"name": "usage", "fn": t_usage, "description": "Show the plan, jobs or credits used and what is left.",
     "annotations": {"readOnlyHint": True, "openWorldHint": True}, "inputSchema": {"type": "object", "properties": {}}},
    {"name": "delete_task", "fn": t_delete,
     "description": "Delete a task's files from PDFTrusted now (otherwise they are deleted within an hour).",
     "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True},
     "inputSchema": {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "string"}}}},
]
BY_NAME = {t["name"]: t for t in TOOLS}


def _result(payload: dict, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=1)}],
            "structuredContent": payload, "isError": error}


def handle(msg: dict) -> dict | None:
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:  # a notification (initialized, cancelled): nothing to answer
        return None
    if method == "initialize":
        res = {"protocolVersion": params.get("protocolVersion") or PROTOCOL,
               "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER, "instructions": INSTRUCTIONS}
    elif method == "ping":
        res = {}
    elif method == "tools/list":
        res = {"tools": [{k: v for k, v in t.items() if k != "fn"} for t in TOOLS]}
    elif method == "tools/call":
        tool = BY_NAME.get(params.get("name"))
        if not tool:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": f"unknown tool {params.get('name')!r}"}}
        try:
            res = _result(tool["fn"](params.get("arguments") or {}))
        except pt.ApiError as e:
            res = _result({"error": {"code": e.code, "message": e.message, **e.extra}}, error=True)
        except KeyError as e:
            res = _result({"error": {"code": "bad_request", "message": f"missing argument {e}"}}, error=True)
        except Exception as e:  # report it, never crash the server
            traceback.print_exc(file=sys.stderr)
            res = _result({"error": {"code": "client_error", "message": str(e)[:300]}}, error=True)
        finally:
            pt._save_cookies()
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            out = handle(msg) if isinstance(msg, dict) else {
                "jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        if out is not None:
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
