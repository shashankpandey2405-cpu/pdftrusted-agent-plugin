"""The MCP server as a client sees it: a subprocess speaking JSON-RPC over stdio, against the fake API of
test_client. Standard library only."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_client import Fake  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


class McpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Fake.state = {"keys": [], "port": self.port}
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.inp = self.dir / "in.pdf"
        self.inp.write_bytes(b"%PDF-1.4 original")

    def session(self, *messages):
        env = {**os.environ, "PDFTRUSTED_API": f"http://127.0.0.1:{self.port}", "PDFTRUSTED_API_KEY": "sk_test_mcp"}
        stdin = "".join(json.dumps(m) + "\n" for m in messages)
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "mcp_server.py")], input=stdin, env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        return [json.loads(line) for line in p.stdout.splitlines()]

    def call(self, i, name, args):
        return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}}

    def test_handshake_and_tool_list(self):
        out = self.session(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
            {"jsonrpc": "2.0", "id": 4, "method": "nope"},
        )
        self.assertEqual([m["id"] for m in out], [1, 2, 3, 4])  # the notification gets no answer
        self.assertEqual(out[0]["result"]["serverInfo"]["name"], "pdftrusted")
        self.assertIn("tools", out[0]["result"]["capabilities"])
        names = [t["name"] for t in out[1]["result"]["tools"]]
        self.assertEqual(names, ["pdf_tools", "pdf_run", "statement_check", "statement_excel", "usage", "delete_task"])
        self.assertTrue(all("fn" not in t and t["inputSchema"]["type"] == "object" for t in out[1]["result"]["tools"]))
        self.assertEqual(out[3]["error"]["code"], -32601)

    def test_run_saves_next_to_the_input(self):
        (res,) = self.session(self.call(1, "pdf_run", {"tool": "compress", "files": str(self.inp),
                                                       "options": {"level": "high"}}))
        r = res["result"]
        self.assertFalse(r["isError"])
        self.assertEqual(pathlib.Path(r["structuredContent"]["output"]).read_bytes(), b"RESULT")
        self.assertEqual(self.inp.read_bytes(), b"%PDF-1.4 original")
        self.assertEqual(Fake.state["task"]["options"], {"level": "high"})

    def test_statement_check_then_reviewed_excel(self):
        (chk,) = self.session(self.call(1, "statement_check", {"file": str(self.inp)}))
        s = chk["result"]["structuredContent"]
        self.assertEqual((s["state"], [r["row"] for r in s["needs_check"]]), ("NEEDS_REVIEW", [1]))
        review = {"by": "A", "corrections": [{"row": 1, "field": "debit", "value": "450.38"}], "approve": []}
        (xl,) = self.session(self.call(2, "statement_excel", {"file": str(self.inp), "review_of": "t1", "review": review}))
        self.assertFalse(xl["result"]["isError"])
        opts = Fake.state["task"]["options"]
        self.assertEqual((opts["format"], opts["review_of"], json.loads(opts["review"])), ("xlsx", "t1", review))

    def test_errors_come_back_as_tool_errors_not_crashes(self):
        out = self.session(self.call(1, "pdf_run", {"tool": "quota", "files": [str(self.inp)]}),
                           self.call(2, "pdf_run", {"files": [str(self.inp)]}),
                           self.call(3, "nope", {}))
        self.assertTrue(out[0]["result"]["isError"])
        self.assertEqual(out[0]["result"]["structuredContent"]["error"]["code"], "quota_exceeded")
        self.assertEqual(out[1]["result"]["structuredContent"]["error"]["code"], "bad_request")
        self.assertEqual(out[2]["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
