#!/usr/bin/env python3
"""Offline check: the mod's command file-name pattern (read from Commands.cs) accepts the core's time-based
10-digit seq and the contract's range, and rejects junk. Run: python3 mod/tests/CmdName/check.py"""
import os, re, sys
src = open(os.path.join(os.path.dirname(__file__), "..", "..", "src", "Commands.cs")).read()
m = re.search(r'NameRx = new Regex\("(.*?)", RegexOptions', src)
rx = re.compile(m.group(1).replace("\\\\", "\\"))
ok = ["cmd-1792950087.json", "cmd-1.json", "cmd-5.json", "cmd-123456789.json", "cmd-9223372036854775.json"]
bad = ["cmd-1792950087.json.tmp", "cmd-.json", "cmd-abc.json", "cmd-12.JSON", "../cmd-1.json", "cmd-1234567890123456789.json"]
fail = [n for n in ok if not rx.match(n)] + [n for n in bad if rx.match(n)]
print("pattern:", rx.pattern, "FAIL: %s" % fail if fail else "OK")
sys.exit(1 if fail else 0)
