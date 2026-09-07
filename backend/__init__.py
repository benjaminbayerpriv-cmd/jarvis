import sys

# Windows redirects stdout/stderr to the OS locale's preferred codepage
# (cp1252 on a German system) rather than UTF-8 unless something says
# otherwise — every print() anywhere in this package that touches an
# umlaut, ß, or any other non-cp1252 character (an em dash, a smart quote)
# either gets silently mangled into "�" or, in stricter contexts, raises
# UnicodeEncodeError outright. reconfigure() is only available on real
# text streams (Python 3.7+); guarded since a frozen/embedded interpreter
# can occasionally hand back something else.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
