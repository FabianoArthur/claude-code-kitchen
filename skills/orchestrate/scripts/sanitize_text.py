#!/usr/bin/env python3
"""
sanitize_text — remove invisible and hidden text from external input.

Removes characters a reader cannot see but a model or a parser can act on: zero-width and
bidi controls, word joiners, soft hyphens, BOM, Unicode tag characters (ASCII smuggling),
variation selectors, invisible fillers, C0/C1 control characters (tab, LF and CR are kept),
and HTML comments. A U+FE0F survives only right after a base character that takes it
(emoji, symbol, digit, # or *).

Accented letters and the rest of the visible text are kept. The count per type goes to
stderr; the cleaned text goes to stdout as UTF-8.

Usage:
    python3 sanitize_text.py [FILE]        # no FILE, or "-": read stdin
    python3 sanitize_text.py --selftest

Exit: 0 = ok · 2 = error (unreadable input, not UTF-8, bad arguments)
"""
import argparse
import re
import sys

HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

# (kind, first codepoint, last codepoint), both ends inclusive.
INVISIBLE_RANGES = [
    ("zero-width", 0x200B, 0x200D),
    ("lrm-rlm-mark", 0x200E, 0x200F),
    ("bidi-embedding", 0x202A, 0x202E),
    ("bidi-isolate", 0x2066, 0x2069),
    ("bom-FEFF", 0xFEFF, 0xFEFF),
    ("soft-hyphen-00AD", 0x00AD, 0x00AD),
    ("word-joiner-2060-2064", 0x2060, 0x2064),
    ("mongolian-vs-180E", 0x180E, 0x180E),
    ("tag-chars", 0xE0000, 0xE007F),
    ("c0-control", 0x0000, 0x0008),
    ("c0-control", 0x000B, 0x000C),
    ("c0-control", 0x000E, 0x001F),
    ("del-007F", 0x007F, 0x007F),
    ("c1-control", 0x0080, 0x009F),
    ("variation-selector", 0xFE00, 0xFE0E),
    ("variation-selector", 0xE0100, 0xE01EF),
    ("invisible-filler", 0x034F, 0x034F),
    ("invisible-filler", 0x115F, 0x1160),
    ("invisible-filler", 0x3164, 0x3164),
    ("invisible-filler", 0xFFA0, 0xFFA0),
    ("invisible-filler", 0xFFF9, 0xFFFB),
]

# U+FE0F survives only if the character right before it (in the input) is one of these.
FE0F_BASE_RANGES = [
    (0x00A9, 0x00A9), (0x00AE, 0x00AE), (0x203C, 0x203C), (0x2049, 0x2049),
    (0x2122, 0x2122), (0x2139, 0x2139), (0x2190, 0x21FF), (0x2300, 0x23FF),
    (0x2460, 0x24FF), (0x25A0, 0x27BF), (0x2900, 0x297F), (0x2B00, 0x2BFF),
    (0x3030, 0x3030), (0x303D, 0x303D), (0x3297, 0x3297), (0x3299, 0x3299),
    (0x1F000, 0x1FAFF),
]
FE0F_BASE_CHARS = set("0123456789#*")


def _kind_of(cp):
    for kind, first, last in INVISIBLE_RANGES:
        if first <= cp <= last:
            return kind
    return None


def _accepts_fe0f(ch):
    if ch in FE0F_BASE_CHARS:
        return True
    cp = ord(ch)
    return any(first <= cp <= last for first, last in FE0F_BASE_RANGES)


def sanitize(text):
    """Return (clean_text, counts_by_kind).

    HTML comments are removed first, so invisible characters inside them are not counted.
    A U+FE0F checks the character before it in the input text: a comment or an invisible
    character right before it counts as "not a base".
    """
    counts = {}

    def count(kind):
        counts[kind] = counts.get(kind, 0) + 1

    comments = list(HTML_COMMENT.finditer(text))
    if comments:
        counts["html-comment"] = len(comments)
    inside_comment = bytearray(len(text))  # 1 = part of a comment, dropped
    for m in comments:
        inside_comment[m.start():m.end()] = b"\x01" * (m.end() - m.start())

    out = []
    for i, ch in enumerate(text):
        if inside_comment[i]:
            continue
        if ch == "\ufe0f":
            if i > 0 and _accepts_fe0f(text[i - 1]):
                out.append(ch)
            else:
                count("fe0f-without-base")
            continue
        kind = _kind_of(ord(ch))
        if kind is None:
            out.append(ch)
        else:
            count(kind)
    return "".join(out), counts


def _summary(counts):
    if not counts:
        return "nothing removed"
    return ", ".join(f"{kind}={counts[kind]}" for kind in sorted(counts))


def selftest():
    cases = [
        ("empty", "", "", {}),
        ("zero-width", "a​b‌c‍d", "abcd", {"zero-width": 3}),
        ("marks and bidi", "a‎b‏c‪d‮e⁦f⁩", "abcdef",
         {"lrm-rlm-mark": 2, "bidi-embedding": 2, "bidi-isolate": 2}),
        ("BOM, soft hyphen, joiners, 180E", "﻿a­b⁠c⁤d᠎e", "abcde",
         {"bom-FEFF": 1, "soft-hyphen-00AD": 1, "word-joiner-2060-2064": 2, "mongolian-vs-180E": 1}),
        ("tag characters", "x\U000E0041\U000E0042y", "xy", {"tag-chars": 2}),
        ("variation selectors and fillers", "a︁b\U000E0100cㅤd", "abcd",
         {"variation-selector": 2, "invisible-filler": 1}),
        ("html comment with hidden text inside", "keep<!-- ​ hidden\nline -->after", "keepafter",
         {"html-comment": 1}),
        ("two html comments", "<!--1--> x <!--2-->", " x ", {"html-comment": 2}),
        ("c0, del and c1 controls; tab, LF, CR kept", "a\x00b\x1bc\x7fd\x9be\tf\ng\rh",
         "abcde\tf\ng\rh", {"c0-control": 2, "del-007F": 1, "c1-control": 1}),
        ("accents kept", "ação, coração, é, ñ, ü, Ç", "ação, coração, é, ñ, ü, Ç", {}),
        ("FE0F kept after an emoji base", "❤️ ok", "❤️ ok", {}),
        ("FE0F kept after a digit, removed after a letter", "a️1️", "a1️",
         {"fe0f-without-base": 1}),
        ("FE0F after an invisible character is removed", "​️", "",
         {"zero-width": 1, "fe0f-without-base": 1}),
    ]
    for name, src, want, want_counts in cases:
        got, counts = sanitize(src)
        if got != want or counts != want_counts:
            print(f"selftest FAIL: {name}: got {got!r} {counts!r}")
            return 1
    print(f"selftest ok ({len(cases)} cases)")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Remove invisible and hidden text from external input.")
    parser.add_argument("file", nargs="?", help='input file; omit or "-" to read stdin')
    parser.add_argument("--selftest", action="store_true", help="run the built-in checks and exit")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()

    try:
        if args.file in (None, "-"):
            raw = sys.stdin.buffer.read()
        else:
            with open(args.file, "rb") as f:
                raw = f.read()
    except OSError as e:
        sys.stderr.write(f"sanitize_text: cannot read input: {e.strerror}\n")
        return 2
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        sys.stderr.write(f"sanitize_text: input is not valid UTF-8 (byte offset {e.start})\n")
        return 2

    clean, counts = sanitize(text)
    sys.stdout.buffer.write(clean.encode("utf-8"))
    sys.stdout.flush()
    sys.stderr.write(f"sanitize_text: removed: {_summary(counts)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
