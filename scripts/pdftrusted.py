#!/usr/bin/env python3
"""PDFTrusted API client for AI agents and scripts — standard library only (Python 3.8+).

    python pdftrusted.py tools [--query word]             list tools, their credits and options
    python pdftrusted.py run TOOL FILE... [-o OUT] [--opt key=value ...]
    python pdftrusted.py statement FILE [--xlsx] [--review review.json --review-of TASK_ID] [-o OUT]
    python pdftrusted.py usage                            jobs / credits left today
    python pdftrusted.py delete TASK_ID                   delete the server copy now (otherwise ~1 hour)

Auth: PDFTRUSTED_API_KEY (free key at https://developers.pdftrusted.com). Without a key the client runs as a guest
(a few jobs a day). PDFTRUSTED_API overrides the base URL (default https://api.pdftrusted.com).

Every command prints one JSON object on stdout; errors are {"error": {"code", "message"}} with exit code 2.
The client never prints file contents; for bank statements it prints the rows that need a check so a person (or the
agent, with the person's confirmation) can correct or approve them.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

VERSION = "0.2.0"
BASE = os.environ.get("PDFTRUSTED_API", "https://api.pdftrusted.com").rstrip("/")
KEY = os.environ.get("PDFTRUSTED_API_KEY", "").strip()
UA = f"pdftrusted-agent-plugin/{VERSION} (+https://developers.pdftrusted.com)"
POLL_LIMIT_S = float(os.environ.get("PDFTRUSTED_TIMEOUT", 900))

# A guest owns its tasks by a cookie. Each command is a new process, so the cookie is kept in a small file between
# runs; without that, a later `statement --xlsx --review-of` or `delete` would come from a "new" guest and the gateway
# could not match it to the reading (the free reviewed export, deleting the server copy). Not used with an API key.
COOKIE_FILE = Path(os.environ.get("PDFTRUSTED_COOKIE_FILE") or (Path.home() / ".pdftrusted" / "cookies.txt"))
_jar = http.cookiejar.MozillaCookieJar(str(COOKIE_FILE))
if not KEY:
    try:
        _jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, http.cookiejar.LoadError):
        pass
_op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))


def _save_cookies() -> None:
    if KEY:
        return
    try:
        COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _jar.save(ignore_discard=True, ignore_expires=True)
    except OSError:
        pass


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None, extra: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra or {}


def _headers(extra: dict | None = None) -> dict:
    h = {"User-Agent": UA, "Accept": "application/json"}
    if KEY:
        h["X-API-Key"] = KEY
    return {**h, **(extra or {})}


def _call(method: str, path: str, body: bytes | None = None, headers: dict | None = None, timeout: float = 120):
    req = urllib.request.Request(BASE + path, data=body, method=method, headers=_headers(headers))
    try:
        with _op.open(req, timeout=timeout) as res:
            return res.status, dict(res.headers), res.read()
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try:
            err = json.loads(raw).get("error") or {}
        except ValueError:
            err = {}
        code = err.get("code") or f"http_{e.code}"
        msg = err.get("message") or f"HTTP {e.code}"
        if e.code == 429 and not KEY:
            msg += " Set PDFTRUSTED_API_KEY (free key: https://developers.pdftrusted.com) for more jobs."
        raise ApiError(code, msg, e.code, {k: v for k, v in err.items() if k not in ("code", "message")}) from None
    except urllib.error.URLError as e:
        raise ApiError("network", f"Cannot reach {BASE}: {e.reason}") from None


def _json(method: str, path: str, payload=None, timeout: float = 120) -> dict:
    body = None if payload is None else json.dumps(payload).encode()
    _, _, raw = _call(method, path, body, {"Content-Type": "application/json"} if body else None, timeout)
    return json.loads(raw or b"{}")


def _multipart(path: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode()
    return head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def _filename(headers: dict, fallback: str) -> str:
    cd = headers.get("Content-Disposition") or headers.get("content-disposition") or ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd, re.I) or re.search(r'filename="?([^";]+)"?', cd)
    name = urllib.parse.unquote(m.group(1)) if m else fallback
    return Path(name).name or fallback


def run_task(tool: str, files: list[Path], options: dict | None = None) -> dict:
    """create -> upload each file -> process -> wait -> returns the task JSON (status done)."""
    for f in files:
        if not f.is_file():
            raise ApiError("bad_file", f"File not found: {f}")
    task = _json("POST", "/v1/tasks", {"tool": tool, "options": options or {}})
    tid = task["task_id"]
    for f in files:
        body, ctype = _multipart(f)
        _call("PUT", f"/v1/tasks/{tid}/upload", body, {"Content-Type": ctype}, timeout=600)
    _, _, raw = _call("POST", f"/v1/tasks/{tid}/process?async=1", timeout=180)
    state = json.loads(raw or b"{}")
    waited, delay = 0.0, 1.0
    while state.get("status") not in ("done", "failed"):
        if waited > POLL_LIMIT_S:
            raise ApiError("timeout", f"Task {tid} is still running after {int(waited)} s; poll GET /v1/tasks/{tid}.")
        time.sleep(delay)
        waited += delay
        delay = min(5.0, delay * 1.5)
        state = _json("GET", f"/v1/tasks/{tid}")
    if state["status"] == "failed":
        raise ApiError(state.get("error") or "failed", state.get("error_message") or "The task failed.", None, {"task_id": tid})
    state["task_id"] = tid
    return state


def download(tid: str, fallback_name: str) -> tuple[bytes, str]:
    _, headers, raw = _call("GET", f"/v1/tasks/{tid}/download", timeout=600)
    ctype = headers.get("Content-Type") or headers.get("content-type") or ""
    if "application/json" in ctype:
        try:
            link = json.loads(raw).get("download_url")
        except ValueError:
            link = None
        if link:  # a signed storage link: fetched without our credentials
            with urllib.request.urlopen(urllib.request.Request(link, headers={"User-Agent": UA}), timeout=600) as res:
                return res.read(), _filename(dict(res.headers), fallback_name)
    return raw, _filename(headers, fallback_name)


def _out_path(out: str | None, inputs: list[Path], name: str, tool: str) -> Path:
    if out and not Path(out).is_dir():
        dest = Path(out)
    else:
        dest = (Path(out) if out else inputs[0].parent) / name
    # never overwrite an input file: a compressed or repaired PDF keeps the input's name
    if any(dest.resolve() == i.resolve() for i in inputs if i.exists()):
        dest = dest.with_name(f"{dest.stem}-{tool}{dest.suffix}")
    return dest


def _opts(pairs: list[str]) -> dict:
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise ApiError("bad_option", f"Option must be key=value: {p}")
        k, v = p.split("=", 1)
        try:
            out[k] = json.loads(v)  # numbers, true/false, lists, objects
        except ValueError:
            out[k] = v
    return out


SYNONYMS = {"excel": "xlsx", "word": "docx", "powerpoint": "pptx", "ppt": "pptx", "image": "img", "jpg": "img",
            "png": "img", "picture": "img", "statement": "bank-statement", "smaller": "compress", "join": "merge"}


def cmd_tools(a) -> dict:
    _, _, raw = _call("GET", "/tool-catalog.json")
    cat = json.loads(raw)
    tools = cat.get("tools") or {}
    items = tools.values() if isinstance(tools, dict) else tools
    q = (a.query or "").lower()
    words = {q, SYNONYMS.get(q, q)} if q else set()
    keys = list(tools) if isinstance(tools, dict) else [None] * len(items)
    rows, seen = [], set()
    for key, t in zip(keys, items):
        name = t.get("canonical") or t.get("tool") or key
        hay = f"{key} {name} {json.dumps(t)}".lower()
        if words and not any(w in hay for w in words):
            continue
        if name in seen:
            continue
        seen.add(name)
        rows.append({"tool": name, "credits": t.get("credits"), "options": t.get("options") or {},
                     "multi_file": t.get("upload") == "files", "needs_option": t.get("needs_option")})
    return {"tools": sorted(rows, key=lambda r: r["tool"] or ""), "count": len(rows), "docs": cat.get("docs")}


def cmd_run(a) -> dict:
    files = [Path(f) for f in a.files]
    st = run_task(a.tool, files, _opts(a.opt))
    data, name = download(st["task_id"], st.get("result_name") or f"{files[0].stem}-{a.tool}.out")
    dest = _out_path(a.out, files, name, a.tool)
    dest.write_bytes(data)
    return {"task_id": st["task_id"], "output": str(dest), "bytes": len(data), "meta": st.get("meta") or {},
            "usage": st.get("usage")}


def _needs_check(statement: dict, limit: int) -> list[dict]:
    out = []
    for i, r in enumerate(statement.get("transactions") or []):
        if r.get("state") == "VERIFIED":
            continue
        out.append({"row": i, "date": r.get("date"), "description": (r.get("description") or "")[:80],
                    "debit": r.get("debit"), "credit": r.get("credit"), "balance": r.get("balance"),
                    "state": r.get("state"), "reasons": r.get("state_reasons"), "page": r.get("page")})
        if len(out) >= limit:
            break
    return out


def cmd_statement(a) -> dict:
    f = Path(a.file)
    if not a.xlsx:
        st = run_task("bank-statement", [f], {"format": "json"})
        data, _ = download(st["task_id"], "statement.json")
        s = json.loads(data)["statement"]
        rows = s.get("transactions") or []
        res = {"task_id": st["task_id"], "state": s.get("state"), "reasons": s.get("state_reasons"),
               "rows": len(rows), "rows_verified": sum(1 for r in rows if r.get("state") == "VERIFIED"),
               "opening_balance": s.get("opening_balance"), "closing_balance": s.get("closing_balance"),
               "needs_check": _needs_check(s, a.limit),
               "next": ("Download the Excel: statement FILE --xlsx --review-of " + st["task_id"]
                        + (" --review review.json (corrections / approvals)" if s.get("state") != "VERIFIED" else ""))}
        if a.out:
            Path(a.out).write_text(json.dumps(s, indent=1), encoding="utf-8")
            res["json"] = a.out
        return res
    opts: dict = {"format": "xlsx"}
    if getattr(a, "review_json", None):  # the MCP server passes the review inline
        opts["review"] = a.review_json
    elif a.review:
        opts["review"] = Path(a.review).read_text(encoding="utf-8")
    if a.review_of:
        opts["review_of"] = a.review_of
    st = run_task("bank-statement", [f], opts)
    data, name = download(st["task_id"], f"{f.stem}.xlsx")
    dest = _out_path(a.out, [f], name if name.endswith(".xlsx") else f"{f.stem}.xlsx", "statement")
    dest.write_bytes(data)
    meta = st.get("meta") or {}
    return {"task_id": st["task_id"], "output": str(dest), "bytes": len(data), "state": meta.get("statement_state"),
            "reasons": meta.get("reason_codes"), "rows": meta.get("transactions"), "rows_verified": meta.get("rows_verified"),
            "usage": st.get("usage")}


def cmd_usage(_a) -> dict:
    return _json("GET", "/v1/me/usage")


def cmd_delete(a) -> dict:
    _call("DELETE", f"/v1/tasks/{a.task_id}")
    return {"deleted": a.task_id}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pdftrusted", description="PDFTrusted API client (JSON in, JSON out).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("tools"); p.add_argument("--query"); p.set_defaults(fn=cmd_tools)
    p = sub.add_parser("run"); p.add_argument("tool"); p.add_argument("files", nargs="+"); p.add_argument("-o", "--out")
    p.add_argument("--opt", action="append", default=[], help="tool option key=value (JSON values allowed)"); p.set_defaults(fn=cmd_run)
    p = sub.add_parser("statement"); p.add_argument("file"); p.add_argument("--xlsx", action="store_true")
    p.add_argument("--review"); p.add_argument("--review-of"); p.add_argument("-o", "--out")
    p.add_argument("--limit", type=int, default=50); p.set_defaults(fn=cmd_statement)
    p = sub.add_parser("usage"); p.set_defaults(fn=cmd_usage)
    p = sub.add_parser("delete"); p.add_argument("task_id"); p.set_defaults(fn=cmd_delete)
    a = ap.parse_args(argv)
    try:
        result = a.fn(a)
        _save_cookies()
        print(json.dumps(result, indent=1, ensure_ascii=False))
        return 0
    except ApiError as e:
        _save_cookies()
        print(json.dumps({"error": {"code": e.code, "message": e.message, **({"status": e.status} if e.status else {}), **e.extra}},
                         indent=1, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
