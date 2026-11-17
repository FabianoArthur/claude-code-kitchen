"""sanitize_text.py — invisible and hidden text removal."""
import subprocess
import sys

from conftest import ORCH, load

st = load(ORCH / "sanitize_text.py")
SCRIPT = ORCH / "sanitize_text.py"


def run(args, stdin=b""):
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin,
                          capture_output=True)


def test_selftest():
    r = run(["--selftest"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert b"selftest ok" in r.stdout


def test_zero_width_and_bidi_removed_with_counts():
    clean, counts = st.sanitize("a​b‮c⁦d")
    assert clean == "abcd"
    assert counts == {"zero-width": 1, "bidi-embedding": 1, "bidi-isolate": 1}


def test_tag_characters_removed():
    clean, counts = st.sanitize("ok\U000E0068\U000E0069")
    assert clean == "ok"
    assert counts == {"tag-chars": 2}


def test_html_comment_removed_and_inner_invisibles_not_counted():
    clean, counts = st.sanitize("before<!-- ​ secret -->after")
    assert clean == "beforeafter"
    assert counts == {"html-comment": 1}


def test_accents_preserved_and_nothing_counted():
    text = "ação, coração, Ação é ótimo: ñandú — “aspas”"
    clean, counts = st.sanitize(text)
    assert clean == text
    assert counts == {}


def test_tab_lf_cr_kept_and_other_controls_removed():
    clean, counts = st.sanitize("a\x00\tb\r\n\x1bc")
    assert clean == "a\tb\r\nc"
    assert counts == {"c0-control": 2}


def test_fe0f_only_after_a_base_character():
    assert st.sanitize("❤️")[0] == "❤️"
    clean, counts = st.sanitize("a️")
    assert clean == "a"
    assert counts == {"fe0f-without-base": 1}


def test_stdin_to_stdout_and_summary_on_stderr():
    r = run([], stdin="olá​ mundo".encode("utf-8"))
    assert r.returncode == 0
    assert r.stdout.decode("utf-8") == "olá mundo"
    assert b"sanitize_text: removed: zero-width=1" in r.stderr


def test_file_argument(tmp_path):
    src = tmp_path / "in.md"
    src.write_bytes("x­ y\n".encode("utf-8"))
    r = run([str(src)])
    assert r.returncode == 0
    assert r.stdout.decode("utf-8") == "x y\n"
    assert b"soft-hyphen-00AD=1" in r.stderr


def test_nothing_removed_message():
    r = run([], stdin=b"plain text\n")
    assert r.returncode == 0
    assert r.stdout == b"plain text\n"
    assert b"nothing removed" in r.stderr


def test_invalid_utf8_is_refused():
    r = run([], stdin=b"\xff\xfe bad")
    assert r.returncode == 2
    assert r.stdout == b""
    assert b"not valid UTF-8" in r.stderr


def test_missing_file_is_refused(tmp_path):
    r = run([str(tmp_path / "nope.md")])
    assert r.returncode == 2
    assert b"cannot read input" in r.stderr
