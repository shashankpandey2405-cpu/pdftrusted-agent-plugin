"""The client against a fake PDFTrusted API: the 4-step task flow, a signed-link download, polling, errors, and the
promise that an input file is never overwritten. Standard library only: `python -m unittest discover tests`."""
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Fake(BaseHTTPRequestHandler):
    state = {}

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", headers=None):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        s = Fake.state
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        if self.path == "/v1/tasks":
            req = json.loads(body)
            s["keys"].append(self.headers.get("X-API-Key"))
            if req["tool"] == "quota":
                return self._send(429, {"error": {"code": "quota_exceeded", "message": "Used all jobs today."}})
            s["task"] = {"tool": req["tool"], "options": req.get("options"), "uploads": 0, "polls": 0}
            return self._send(201, {"task_id": "t1", "upload_url": "/v1/tasks/t1/upload"})
        if self.path.startswith("/v1/tasks/t1/process"):
            return self._send(202, {"status": "processing"})
        self._send(404, {"error": {"code": "not_found", "message": "no"}})

    def do_PUT(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        assert b'name="file"' in body
        Fake.state["task"]["uploads"] += 1
        self._send(200, {"status": "uploaded"})

    def do_GET(self):
        s = Fake.state
        if self.path == "/v1/tasks/t1":
            s["task"]["polls"] += 1
            if s["task"]["polls"] < 2:
                return self._send(200, {"status": "processing"})
            return self._send(200, {"status": "done", "result_name": "in.pdf",
                                    "meta": {"statement_state": "VERIFIED", "transactions": 3, "rows_verified": 3}})
        if self.path == "/v1/tasks/t1/download":
            if s["task"]["tool"] == "bank-statement" and (s["task"]["options"] or {}).get("format") == "json":
                st = {"statement": {"state": "NEEDS_REVIEW", "state_reasons": ["ROWS_MISMATCH"], "transactions": [
                    {"state": "VERIFIED", "date": "2026-01-02"},
                    {"state": "NEEDS_REVIEW", "date": "2026-01-03", "description": "NEFT", "debit": "451.38",
                     "credit": None, "balance": "97804.92", "state_reasons": ["BALANCE_MISMATCH"], "page": 1}]}}
                return self._send(200, st)
            if s.get("signed"):
                return self._send(200, {"download_url": f"http://127.0.0.1:{s['port']}/r2/out"})
            return self._send(200, b"RESULT", "application/pdf", {"Content-Disposition": 'attachment; filename="in.pdf"'})
        if self.path == "/r2/out":
            s["r2_auth"] = self.headers.get("X-API-Key")
            return self._send(200, b"FROM-R2", "application/pdf", {"Content-Disposition": 'attachment; filename="in.pdf"'})
        self._send(404, {"error": {"code": "not_found", "message": "no"}})


class ClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        port = cls.srv.server_address[1]
        os.environ["PDFTRUSTED_API"] = f"http://127.0.0.1:{port}"
        os.environ["PDFTRUSTED_API_KEY"] = "sk_test_unit"
        spec = importlib.util.spec_from_file_location("pdftrusted", ROOT / "scripts" / "pdftrusted.py")
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)
        cls.port = port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Fake.state = {"keys": [], "port": self.port}
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.inp = self.dir / "in.pdf"
        self.inp.write_bytes(b"%PDF-1.4 original")

    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = self.m.main(list(args))
        return code, json.loads(buf.getvalue())

    def test_run_uploads_waits_downloads_and_never_overwrites_the_input(self):
        code, out = self.run_cli("run", "compress", str(self.inp))
        self.assertEqual(code, 0)
        self.assertEqual(self.inp.read_bytes(), b"%PDF-1.4 original")  # untouched
        self.assertEqual(pathlib.Path(out["output"]).name, "in-compress.pdf")
        self.assertEqual(pathlib.Path(out["output"]).read_bytes(), b"RESULT")
        self.assertEqual(Fake.state["task"]["uploads"], 1)
        self.assertGreaterEqual(Fake.state["task"]["polls"], 2)  # waited for the job
        self.assertEqual(Fake.state["keys"], ["sk_test_unit"])

    def test_signed_link_is_fetched_without_our_key(self):
        Fake.state["signed"] = True
        code, out = self.run_cli("run", "compress", str(self.inp), "-o", str(self.dir / "small.pdf"))
        self.assertEqual(code, 0)
        self.assertEqual((self.dir / "small.pdf").read_bytes(), b"FROM-R2")
        self.assertIsNone(Fake.state.get("r2_auth"))

    def test_options_are_json_values(self):
        self.run_cli("run", "rotate", str(self.inp), "--opt", "angle=90", "--opt", "pages=1-3", "--opt", 'x={"a":1}')
        self.assertEqual(Fake.state["task"]["options"], {"angle": 90, "pages": "1-3", "x": {"a": 1}})

    def test_statement_lists_only_the_rows_that_need_a_check(self):
        code, out = self.run_cli("statement", str(self.inp))
        self.assertEqual(code, 0)
        self.assertEqual(out["state"], "NEEDS_REVIEW")
        self.assertEqual([r["row"] for r in out["needs_check"]], [1])
        self.assertIn("--review-of t1", out["next"])

    def test_reviewed_export_sends_review_and_review_of(self):
        review = self.dir / "review.json"
        review.write_text('{"by": "x", "approve": [1]}')
        code, out = self.run_cli("statement", str(self.inp), "--xlsx", "--review", str(review), "--review-of", "t0")
        self.assertEqual(code, 0)
        opts = Fake.state["task"]["options"]
        self.assertEqual((opts["format"], opts["review_of"], json.loads(opts["review"])["approve"]), ("xlsx", "t0", [1]))
        self.assertEqual(out["state"], "VERIFIED")

    def test_errors_are_json_with_exit_code_2(self):
        code, out = self.run_cli("run", "quota", str(self.inp))
        self.assertEqual(code, 2)
        self.assertEqual(out["error"]["code"], "quota_exceeded")
        code, out = self.run_cli("run", "compress", str(self.dir / "missing.pdf"))
        self.assertEqual((code, out["error"]["code"]), (2, "bad_file"))


class GuestCookieTest(unittest.TestCase):
    """Without a key each command is a new process: the guest cookie must survive between runs, or a later
    reviewed export / delete comes from a different guest."""

    def load(self, env):
        old = {k: os.environ.get(k) for k in env}
        os.environ.update({k: v for k, v in env.items() if v is not None})
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
        try:
            spec = importlib.util.spec_from_file_location("pdftrusted_guest", ROOT / "scripts" / "pdftrusted.py")
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_guest_cookie_is_kept_between_runs_and_never_with_a_key(self):
        import http.cookiejar
        jar_file = pathlib.Path(tempfile.mkdtemp()) / "c" / "cookies.txt"
        env = {"PDFTRUSTED_API_KEY": None, "PDFTRUSTED_COOKIE_FILE": str(jar_file)}
        first = self.load(env)
        first._jar.set_cookie(http.cookiejar.Cookie(0, "gw_guest", "abc", None, False, "api.example", True, False,
                                                    "/", True, True, None, False, None, None, {}))
        first._save_cookies()
        self.assertTrue(jar_file.exists())
        second = self.load(env)
        self.assertEqual([c.value for c in second._jar], ["abc"])
        keyed = self.load({"PDFTRUSTED_API_KEY": "sk_x", "PDFTRUSTED_COOKIE_FILE": str(jar_file)})
        self.assertEqual(list(keyed._jar), [])


if __name__ == "__main__":
    unittest.main()
