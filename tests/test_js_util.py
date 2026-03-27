"""Tests for JS utility functions via a lightweight Node.js runner.

Loads server/js/util.js and verifies the pure functions (formatters,
escaping, time helpers) produce correct output. Requires Node.js.
"""

import json
import subprocess
from pathlib import Path

import pytest

JS_DIR = Path(__file__).resolve().parent.parent / "server" / "js"
UTIL_JS = (JS_DIR / "util.js").read_text()

# Minimal DOM shim so esc() works in Node
SHIM = """
const document = { createElement: () => ({ set textContent(v) { this._t = v; }, get innerHTML() { return this._t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }}) };
"""


def _run_js(expr: str) -> str:
    """Evaluate a JS expression in Node with util.js loaded, return result as string."""
    script = SHIM + UTIL_JS + f"\nprocess.stdout.write(JSON.stringify({expr}));"
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=5)
    if r.returncode != 0:
        pytest.fail(f"Node.js error: {r.stderr}")
    return json.loads(r.stdout)


class TestFmtDur:
    def test_zero(self):
        assert _run_js("fmtDur(0)") == "0s"

    def test_seconds(self):
        assert _run_js("fmtDur(45)") == "45s"

    def test_minutes(self):
        assert _run_js("fmtDur(150)") == "3m"

    def test_hours(self):
        assert _run_js("fmtDur(3700)") == "1h 2m"

    def test_null(self):
        assert _run_js("fmtDur(null)") == "0s"


class TestFormatDuration:
    def test_minutes(self):
        assert _run_js("formatDuration('2026-01-01T10:00:00Z','2026-01-01T10:05:00Z')") == "5m"

    def test_hours(self):
        assert _run_js("formatDuration('2026-01-01T10:00:00Z','2026-01-01T11:30:00Z')") == "1h 30m"

    def test_missing(self):
        assert _run_js("formatDuration(null, '2026-01-01T10:00:00Z')") == "?"

    def test_negative(self):
        assert _run_js("formatDuration('2026-01-01T11:00:00Z','2026-01-01T10:00:00Z')") == "?"


class TestRelativeTime:
    def test_null(self):
        assert _run_js("relativeTime(null)") == "?"

    def test_future(self):
        assert _run_js("relativeTime('2099-01-01T00:00:00Z')") == "just now"


class TestPrettyProject:
    def test_strips_prefix(self):
        assert _run_js("prettyProject('-Users-alice-projects-frontend')") == "projects/frontend"

    def test_null(self):
        assert _run_js("prettyProject('')") == "?"

    def test_simple(self):
        assert _run_js("prettyProject('my-project')") == "my/project"


class TestEsc:
    def test_html_entities(self):
        assert "<" not in _run_js("esc('<script>alert(1)</script>')")

    def test_safe_string(self):
        assert _run_js("esc('hello')") == "hello"


class TestEscAttr:
    def test_quotes(self):
        result = _run_js("escAttr(\"it's \\\"quoted\\\"\")")
        assert "'" not in result or "&#39;" in result
        assert '"' not in result or "&quot;" in result


class TestTruncate:
    def test_short(self):
        assert _run_js("truncate('hello', 10)") == "hello"

    def test_long(self):
        assert _run_js("truncate('hello world', 5)") == "hello..."


class TestToolPreview:
    def test_read(self):
        assert _run_js("toolPreview({name:'Read',input:{file_path:'/foo/bar.py'}})") == "/foo/bar.py"

    def test_bash(self):
        assert _run_js("toolPreview({name:'Bash',input:{command:'ls -la'}})") == "ls -la"

    def test_grep(self):
        assert _run_js("toolPreview({name:'Grep',input:{pattern:'TODO',path:'src/'}})") == "/TODO/ src/"


class TestExtractBlocks:
    def test_string_content(self):
        result = _run_js("extractBlocks({message:{content:'hello'}})")
        assert result == [{"type": "text", "text": "hello"}]

    def test_array_content(self):
        result = _run_js("extractBlocks({message:{content:[{type:'text',text:'hi'}]}})")
        assert result == [{"type": "text", "text": "hi"}]

    def test_empty(self):
        assert _run_js("extractBlocks({})") == []
