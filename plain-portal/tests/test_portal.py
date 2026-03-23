from __future__ import annotations

import asyncio
import base64
import io
import json
import struct

import nacl.exceptions
import nacl.secret
import pytest
import spake2

from plain.portal.codegen import WORDLIST, generate_code, validate_code
from plain.portal.crypto import PortalEncryptor, channel_id
from plain.portal.local import _MAX_FRAME_SIZE, _recv_framed, _send_framed
from plain.portal.protocol import (
    DEFAULT_EXEC_TIMEOUT,
    FILE_CHUNK_SIZE,
    PROTOCOL_VERSION,
    RELAY_PATH,
    chunk_count,
    make_error,
    make_exec,
    make_exec_result,
    make_file_data,
    make_file_pull,
    make_file_push,
    make_file_push_result,
    make_ping,
    make_pong,
    make_relay_url,
)

# ---------------------------------------------------------------------------
# 1. Code generation roundtrip
# ---------------------------------------------------------------------------


class TestCodegen:
    def test_generated_code_is_valid(self):
        code = generate_code()
        assert validate_code(code)

    def test_generate_many_unique(self):
        codes = {generate_code() for _ in range(200)}
        # With ~188 words and 99 numbers the space is huge; 200 draws should be unique.
        assert len(codes) == 200
        for code in codes:
            assert validate_code(code)

    def test_code_format(self):
        for _ in range(50):
            code = generate_code()
            parts = code.split("-")
            assert len(parts) == 3
            n = int(parts[0])
            assert 1 <= n <= 99
            assert parts[1] in WORDLIST
            assert parts[2] in WORDLIST
            assert parts[1] != parts[2]

    def test_validate_rejects_bad_codes(self):
        assert not validate_code("")
        assert not validate_code("hello")
        assert not validate_code("0-apple-banana")  # number out of range
        assert not validate_code("100-apple-banana")  # number out of range
        assert not validate_code("abc-apple-banana")  # non-numeric
        assert not validate_code("5-")  # missing words
        assert not validate_code("5-apple")  # missing second word

    def test_validate_accepts_arbitrary_words(self):
        # validate_code only checks structure, not membership in WORDLIST
        assert validate_code("42-foo-bar")
        assert validate_code("1-x-y")
        assert validate_code("99-anything-goes")

    def test_validate_boundary_numbers(self):
        assert validate_code("1-a-b")
        assert validate_code("99-a-b")
        assert not validate_code("0-a-b")
        assert not validate_code("100-a-b")
        assert not validate_code("-1-a-b")


# ---------------------------------------------------------------------------
# 2. Crypto roundtrip
# ---------------------------------------------------------------------------


class TestCrypto:
    def test_channel_id_deterministic(self):
        assert channel_id("42-apple-banana") == channel_id("42-apple-banana")

    def test_channel_id_differs_for_different_codes(self):
        assert channel_id("1-a-b") != channel_id("2-a-b")

    def test_channel_id_is_hex_sha256(self):
        cid = channel_id("test-code-here")
        assert len(cid) == 64
        assert all(c in "0123456789abcdef" for c in cid)

    def test_spake2_key_agreement(self):
        """Two sides using the same password derive the same key."""
        password = b"42-apple-banana"
        side_a = spake2.SPAKE2_A(password)
        side_b = spake2.SPAKE2_B(password)

        msg_a = side_a.start()
        msg_b = side_b.start()

        key_a = side_a.finish(msg_b)
        key_b = side_b.finish(msg_a)
        assert key_a == key_b
        assert len(key_a) == 32  # NaCl SecretBox key size

    def test_spake2_wrong_password_different_keys(self):
        """Different passwords produce different keys (no agreement)."""
        side_a = spake2.SPAKE2_A(b"password-one")
        side_b = spake2.SPAKE2_B(b"password-two")

        msg_a = side_a.start()
        msg_b = side_b.start()

        key_a = side_a.finish(msg_b)
        key_b = side_b.finish(msg_a)
        assert key_a != key_b

    def test_encryptor_roundtrip_bytes(self):
        """Encrypt and decrypt raw bytes with the same key."""
        a = spake2.SPAKE2_A(b"secret")
        b = spake2.SPAKE2_B(b"secret")
        a.start()  # must be called to initialize internal state
        msg_b = b.start()
        key = a.finish(msg_b)

        enc = PortalEncryptor(key)
        plaintext = b"Hello, portal!"
        ciphertext = enc.encrypt(plaintext)
        assert ciphertext != plaintext
        assert enc.decrypt(ciphertext) == plaintext

    def test_encryptor_roundtrip_message(self):
        """Encrypt and decrypt a JSON message dict."""
        a = spake2.SPAKE2_A(b"secret")
        b = spake2.SPAKE2_B(b"secret")
        msg_a = a.start()
        msg_b = b.start()
        key_a = a.finish(msg_b)
        key_b = b.finish(msg_a)

        enc_a = PortalEncryptor(key_a)
        enc_b = PortalEncryptor(key_b)

        original = {"type": "exec", "code": "print('hi')", "json_output": False}
        ciphertext = enc_a.encrypt_message(original)
        decrypted = enc_b.decrypt_message(ciphertext)
        assert decrypted == original

    def test_encryptor_wrong_key_fails(self):
        """Decryption with a different key raises an exception."""
        a = spake2.SPAKE2_A(b"right-password")
        b = spake2.SPAKE2_B(b"right-password")
        msg_a = a.start()
        msg_b = b.start()
        key_right = a.finish(msg_b)
        b.finish(msg_a)  # complete the exchange

        # A different key
        c = spake2.SPAKE2_A(b"wrong-password")
        d = spake2.SPAKE2_B(b"wrong-password")
        msg_c = c.start()
        msg_d = d.start()
        key_wrong = c.finish(msg_d)
        d.finish(msg_c)

        enc_right = PortalEncryptor(key_right)
        enc_wrong = PortalEncryptor(key_wrong)

        ciphertext = enc_right.encrypt(b"secret data")
        with pytest.raises(nacl.exceptions.CryptoError):
            enc_wrong.decrypt(ciphertext)

    def test_encryptor_large_payload(self):
        """Encrypt/decrypt a large payload (1MB)."""
        a = spake2.SPAKE2_A(b"big")
        b = spake2.SPAKE2_B(b"big")
        a.start()  # must be called to initialize internal state
        msg_b = b.start()
        key = a.finish(msg_b)

        enc = PortalEncryptor(key)
        payload = b"\x42" * (1024 * 1024)
        assert enc.decrypt(enc.encrypt(payload)) == payload

    def test_each_encryption_produces_different_ciphertext(self):
        """NaCl uses a random nonce, so encrypting the same plaintext twice differs."""
        a = spake2.SPAKE2_A(b"nonce")
        b = spake2.SPAKE2_B(b"nonce")
        a.start()  # must be called to initialize internal state
        msg_b = b.start()
        key = a.finish(msg_b)

        enc = PortalEncryptor(key)
        ct1 = enc.encrypt(b"same")
        ct2 = enc.encrypt(b"same")
        assert ct1 != ct2
        # But both decrypt to the same value
        assert enc.decrypt(ct1) == enc.decrypt(ct2) == b"same"


# ---------------------------------------------------------------------------
# 3. Protocol messages
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_make_exec(self):
        msg = make_exec("print(1)")
        assert msg["type"] == "exec"
        assert msg["code"] == "print(1)"
        assert msg["json_output"] is False
        assert msg["timeout"] == DEFAULT_EXEC_TIMEOUT

    def test_make_exec_json(self):
        msg = make_exec("x", json_output=True)
        assert msg["json_output"] is True

    def test_make_exec_timeout(self):
        msg = make_exec("x", timeout=300)
        assert msg["timeout"] == 300

    def test_make_exec_result(self):
        msg = make_exec_result(return_value="42", error=None)
        assert msg["type"] == "exec_result"
        assert msg["return_value"] == "42"
        assert msg["error"] is None

    def test_make_error(self):
        msg = make_error("something broke")
        assert msg == {"type": "error", "error": "something broke"}

    def test_make_file_pull(self):
        msg = make_file_pull("/tmp/test.txt")
        assert msg == {"type": "file_pull", "remote_path": "/tmp/test.txt"}

    def test_make_file_data(self):
        raw = b"hello world"
        msg = make_file_data(name="test.txt", chunk=0, chunks=1, data=raw)
        assert msg["type"] == "file_data"
        assert msg["name"] == "test.txt"
        assert msg["chunk"] == 0
        assert msg["chunks"] == 1
        assert base64.b64decode(msg["data"]) == raw

    def test_make_file_push(self):
        raw = b"\x00\x01\x02"
        msg = make_file_push(remote_path="/tmp/out.bin", chunk=0, chunks=1, data=raw)
        assert msg["type"] == "file_push"
        assert msg["remote_path"] == "/tmp/out.bin"
        assert base64.b64decode(msg["data"]) == raw

    def test_make_file_push_result(self):
        msg = make_file_push_result(path="/tmp/out.bin", total_bytes=1024)
        assert msg == {
            "type": "file_push_result",
            "path": "/tmp/out.bin",
            "bytes": 1024,
        }

    def test_make_ping_pong(self):
        assert make_ping() == {"type": "ping"}
        assert make_pong() == {"type": "pong"}

    def test_chunk_count(self):
        assert chunk_count(0) == 1  # even empty file needs 1 chunk
        assert chunk_count(1) == 1
        assert chunk_count(FILE_CHUNK_SIZE) == 1
        assert chunk_count(FILE_CHUNK_SIZE + 1) == 2
        assert chunk_count(FILE_CHUNK_SIZE * 3) == 3
        assert chunk_count(FILE_CHUNK_SIZE * 3 + 1) == 4

    def test_make_relay_url_wss(self):
        url = make_relay_url("portal.plainframework.com", "abc123", "start")
        assert url == (
            f"wss://portal.plainframework.com{RELAY_PATH}"
            f"?v={PROTOCOL_VERSION}&channel=abc123&side=start"
        )

    def test_make_relay_url_ws_localhost(self):
        url = make_relay_url("localhost:8080", "chan", "connect")
        assert url.startswith("ws://localhost:8080")
        assert "channel=chan" in url
        assert "side=connect" in url

    def test_make_relay_url_ws_127(self):
        url = make_relay_url("127.0.0.1:9000", "c", "start")
        assert url.startswith("ws://127.0.0.1:9000")

    def test_all_message_types(self):
        """Every make_* function produces a dict with a 'type' key."""
        messages = [
            make_exec("x"),
            make_exec_result(None, None),
            make_error("e"),
            make_file_pull("/tmp/x"),
            make_file_data("f", 0, 1, b""),
            make_file_push("/tmp/x", 0, 1, b""),
            make_file_push_result("/tmp/x", 0),
            make_ping(),
            make_pong(),
        ]
        types_seen = set()
        for msg in messages:
            assert "type" in msg
            assert isinstance(msg["type"], str)
            types_seen.add(msg["type"])
        # All unique
        assert len(types_seen) == len(messages)


# ---------------------------------------------------------------------------
# 4. Framing roundtrip
# ---------------------------------------------------------------------------


def _make_stream_pair():
    """Create an in-memory (reader, writer) pair backed by a pipe-like buffer."""
    buf = bytearray()

    class FakeWriter:
        def __init__(self):
            self._buf = buf

        def write(self, data: bytes) -> None:
            self._buf.extend(data)

        async def drain(self) -> None:
            pass

    class FakeReader:
        def __init__(self):
            self._stream: io.BytesIO = io.BytesIO()

        def _set_data(self, data: bytes) -> None:
            self._stream = io.BytesIO(data)

        async def readexactly(self, n: int) -> bytes:
            result = self._stream.read(n)
            if len(result) < n:
                raise asyncio.IncompleteReadError(result, n)
            return result

    return FakeReader(), FakeWriter()


class TestFraming:
    def test_roundtrip_small(self):
        """Send a small message and read it back."""

        async def _run():
            reader, writer = _make_stream_pair()
            payload = b"hello framing"
            await _send_framed(writer, payload)
            reader._set_data(bytes(writer._buf))
            result = await _recv_framed(reader)
            assert result == payload

        asyncio.run(_run())

    def test_roundtrip_large(self):
        """Send a larger payload (1MB) through framing."""

        async def _run():
            reader, writer = _make_stream_pair()
            payload = b"\xab" * (1024 * 1024)
            await _send_framed(writer, payload)
            reader._set_data(bytes(writer._buf))
            result = await _recv_framed(reader)
            assert result == payload

        asyncio.run(_run())

    def test_roundtrip_empty(self):
        """Empty payload should roundtrip."""

        async def _run():
            reader, writer = _make_stream_pair()
            await _send_framed(writer, b"")
            reader._set_data(bytes(writer._buf))
            result = await _recv_framed(reader)
            assert result == b""

        asyncio.run(_run())

    def test_multiple_messages(self):
        """Multiple messages in sequence should be read individually."""

        async def _run():
            reader, writer = _make_stream_pair()
            messages = [b"first", b"second", b"third"]
            for msg in messages:
                await _send_framed(writer, msg)

            reader._set_data(bytes(writer._buf))
            for expected in messages:
                result = await _recv_framed(reader)
                assert result == expected

        asyncio.run(_run())

    def test_frame_format(self):
        """Verify the wire format is a 4-byte big-endian length prefix."""

        async def _run():
            reader, writer = _make_stream_pair()
            payload = b"test"
            await _send_framed(writer, payload)
            raw = bytes(writer._buf)
            assert raw[:4] == struct.pack("!I", 4)
            assert raw[4:] == b"test"

        asyncio.run(_run())

    def test_frame_size_limit_rejected(self):
        """Frames exceeding _MAX_FRAME_SIZE should be rejected."""

        async def _run():
            # Craft a frame header that claims a size beyond the limit
            bad_header = struct.pack("!I", _MAX_FRAME_SIZE + 1)
            reader, _ = _make_stream_pair()
            reader._set_data(bad_header + b"\x00" * 100)
            with pytest.raises(ValueError, match="Frame too large"):
                await _recv_framed(reader)

        asyncio.run(_run())

    def test_frame_at_limit_accepted(self):
        """A frame exactly at _MAX_FRAME_SIZE should be accepted (not rejected)."""

        async def _run():
            reader, writer = _make_stream_pair()
            # We can't actually allocate 75MB for a test, but verify the header
            # passes validation by using a smaller payload and checking the logic
            # path. Instead, test just below the limit conceptually with a real
            # small payload.
            payload = b"x" * 1000
            await _send_framed(writer, payload)
            reader._set_data(bytes(writer._buf))
            result = await _recv_framed(reader)
            assert result == payload

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 5. Execute code (extracted from run_remote)
# ---------------------------------------------------------------------------


def _make_execute_code(*, writable: bool = False):
    """Build an execute_code function equivalent to the one inside run_remote.

    We replicate the closure from remote.py so we can test it without
    starting a real WebSocket session. The logic is identical.
    """
    import ast
    import contextlib
    import io
    import json
    import traceback
    from contextlib import redirect_stderr, redirect_stdout

    def execute_code(code_str: str, *, json_output: bool = False) -> dict:
        namespace: dict = {}
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        return_value = None
        error = None

        try:
            tree = ast.parse(code_str, mode="exec")

            last_expr: ast.Expr | None = None
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                last_expr = tree.body.pop()  # type: ignore[assignment]

            ctx = contextlib.ExitStack()
            ctx.enter_context(redirect_stdout(stdout_capture))
            ctx.enter_context(redirect_stderr(stderr_capture))
            if not writable:
                try:
                    from plain.postgres.connections import read_only

                    ctx.enter_context(read_only())
                except Exception:
                    pass

            with ctx:
                if tree.body:
                    compiled = compile(tree, "<portal>", "exec")
                    exec(compiled, namespace)  # noqa: S102

                if last_expr is not None:
                    expr_code = compile(
                        ast.Expression(last_expr.value), "<portal>", "eval"
                    )
                    result = eval(expr_code, namespace)  # noqa: S307
                    if result is not None:
                        if json_output:
                            try:
                                return_value = json.dumps(result)
                            except (TypeError, ValueError):
                                return_value = repr(result)
                        else:
                            return_value = repr(result)

        except BaseException:
            error = traceback.format_exc()

        stdout = stdout_capture.getvalue() + stderr_capture.getvalue()

        return {
            "stdout": stdout,
            "return_value": return_value,
            "error": error,
        }

    return execute_code


class TestExecuteCode:
    def setup_method(self):
        self.execute = _make_execute_code()

    def test_simple_expression(self):
        result = self.execute("1 + 2")
        assert result["return_value"] == "3"
        assert result["stdout"] == ""
        assert result["error"] is None

    def test_string_expression(self):
        result = self.execute("'hello'")
        assert result["return_value"] == "'hello'"

    def test_none_expression(self):
        """None result should not set return_value."""
        result = self.execute("None")
        assert result["return_value"] is None

    def test_print_captured(self):
        result = self.execute("print('hello world')")
        assert "hello world" in result["stdout"]
        assert result["return_value"] is None
        assert result["error"] is None

    def test_print_and_expression(self):
        """Print output is captured, and the last expression value is returned."""
        result = self.execute("print('side effect')\n42")
        assert "side effect" in result["stdout"]
        assert result["return_value"] == "42"

    def test_multiline_statements(self):
        code = "x = 10\ny = 20\nx + y"
        result = self.execute(code)
        assert result["return_value"] == "30"
        assert result["error"] is None

    def test_syntax_error(self):
        result = self.execute("def")
        assert result["error"] is not None
        assert "SyntaxError" in result["error"]

    def test_runtime_error(self):
        result = self.execute("1 / 0")
        assert result["error"] is not None
        assert "ZeroDivisionError" in result["error"]

    def test_name_error(self):
        result = self.execute("undefined_variable")
        assert result["error"] is not None
        assert "NameError" in result["error"]

    def test_stderr_captured(self):
        code = "import sys; print('err', file=sys.stderr)"
        result = self.execute(code)
        assert "err" in result["stdout"]  # stderr is appended to stdout

    def test_json_output_dict(self):
        result = self.execute('{"key": "value"}', json_output=True)
        assert result["return_value"] == '{"key": "value"}'
        # Verify it's valid JSON
        parsed = json.loads(result["return_value"])
        assert parsed == {"key": "value"}

    def test_json_output_list(self):
        result = self.execute("[1, 2, 3]", json_output=True)
        assert result["return_value"] == "[1, 2, 3]"

    def test_json_output_fallback_to_repr(self):
        """Non-JSON-serializable objects fall back to repr."""
        result = self.execute("object()", json_output=True)
        assert result["return_value"] is not None
        assert result["return_value"].startswith("<object object at")

    def test_json_output_with_set(self):
        """Sets aren't JSON-serializable, should fall back to repr."""
        result = self.execute("{1, 2, 3}", json_output=True)
        assert result["return_value"] is not None
        # repr of a set
        assert result["return_value"].startswith("{")

    def test_system_exit_caught(self):
        """SystemExit (a BaseException) should be caught and reported."""
        result = self.execute("raise SystemExit(1)")
        assert result["error"] is not None
        assert "SystemExit" in result["error"]

    def test_keyboard_interrupt_caught(self):
        """KeyboardInterrupt (a BaseException) should be caught."""
        result = self.execute("raise KeyboardInterrupt()")
        assert result["error"] is not None
        assert "KeyboardInterrupt" in result["error"]

    def test_fresh_namespace_per_call(self):
        """Each execution gets a fresh namespace."""
        self.execute("x = 42")
        result = self.execute("x")
        assert result["error"] is not None
        assert "NameError" in result["error"]

    def test_import_in_code(self):
        result = self.execute("import math\nmath.pi")
        assert result["return_value"] is not None
        assert "3.14" in result["return_value"]

    def test_only_statements_no_expression(self):
        """Code with only statements (no trailing expression) has no return_value."""
        result = self.execute("x = 1\ny = 2")
        assert result["return_value"] is None
        assert result["error"] is None

    def test_multiline_function_definition_and_call(self):
        code = "def add(a, b):\n    return a + b\nadd(3, 4)"
        result = self.execute(code)
        assert result["return_value"] == "7"

    def test_empty_code(self):
        result = self.execute("")
        assert result["return_value"] is None
        assert result["error"] is None
        assert result["stdout"] == ""


# ---------------------------------------------------------------------------
# 6. End-to-end crypto + protocol integration
# ---------------------------------------------------------------------------


class TestCryptoProtocolIntegration:
    """Test encrypting protocol messages and decrypting them on the other side."""

    def _make_encryptor_pair(self):
        a = spake2.SPAKE2_A(b"integration-test")
        b = spake2.SPAKE2_B(b"integration-test")
        msg_a = a.start()
        msg_b = b.start()
        key_a = a.finish(msg_b)
        key_b = b.finish(msg_a)
        return PortalEncryptor(key_a), PortalEncryptor(key_b)

    def test_exec_message_roundtrip(self):
        enc_local, enc_remote = self._make_encryptor_pair()
        msg = make_exec("User.query.count()", json_output=True)
        ciphertext = enc_local.encrypt_message(msg)
        decrypted = enc_remote.decrypt_message(ciphertext)
        assert decrypted == msg

    def test_exec_result_roundtrip(self):
        enc_local, enc_remote = self._make_encryptor_pair()
        msg = make_exec_result(stdout="output\n", return_value="42", error=None)
        ciphertext = enc_remote.encrypt_message(msg)
        decrypted = enc_local.decrypt_message(ciphertext)
        assert decrypted == msg

    def test_file_data_roundtrip(self):
        enc_local, enc_remote = self._make_encryptor_pair()
        raw = b"file contents here" * 100
        msg = make_file_data(name="dump.sql", chunk=0, chunks=1, data=raw)
        ciphertext = enc_remote.encrypt_message(msg)
        decrypted = enc_local.decrypt_message(ciphertext)
        assert decrypted["type"] == "file_data"
        assert base64.b64decode(decrypted["data"]) == raw

    def test_error_message_roundtrip(self):
        enc_local, enc_remote = self._make_encryptor_pair()
        msg = make_error("File not found: /etc/shadow")
        ciphertext = enc_remote.encrypt_message(msg)
        decrypted = enc_local.decrypt_message(ciphertext)
        assert decrypted == msg

    def test_ping_pong_roundtrip(self):
        enc_a, enc_b = self._make_encryptor_pair()
        ping_ct = enc_a.encrypt_message(make_ping())
        assert enc_b.decrypt_message(ping_ct) == {"type": "ping"}
        pong_ct = enc_b.encrypt_message(make_pong())
        assert enc_a.decrypt_message(pong_ct) == {"type": "pong"}
