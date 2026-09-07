"""Behaviour harness for Jarvis.

Measures the thing that actually matters: given a spoken sentence, does the
right tool really run, and does Jarvis avoid claiming it did something it
didn't? Tool side effects are stubbed so the suite can run repeatedly
without opening apps or typing into windows.

    python3 test_jarvis.py            # one pass
    python3 test_jarvis.py 3          # three passes, for flaky behaviour
"""

import re
import sys
from collections import defaultdict

from backend import llm_client, tools

# Spoken replies get read aloud — an emoji there is either skipped oddly by
# the TTS or read out as a symbol name, neither of which anyone wants.
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
)

# (spoken input, expected tool or None for "must not call any tool")
CASES = [
    ("Wie ist das Wetter in Hamburg?", "get_weather"),
    ("Wie ist das Wetter gerade in Berlin?", "get_weather"),
    ("Wie spät ist es?", "get_time"),
    ("Welcher Wochentag ist heute?", "get_time"),
    ("Notiere: Auto waschen", "add_note"),
    ("Merk dir: Zahnarzttermin verschieben", "add_note"),
    ("Öffne github.com", "open_url"),
    ("Mach mal youtube.com auf", "open_url"),
    ("Mach mir Discord auf", "open_app"),
    ("Öffne die Notizen", "open_app"),
    # Decisiveness: act on the obvious interpretation, don't ask what to
    # search for or which page is meant. Either directly opening
    # youtube.com or opening a (possibly empty) YouTube search counts —
    # what matters is that no clarifying question comes back instead.
    ("Mach YouTube auf", ("open_url", "youtube_search")),
    ("Kannst du YouTube öffnen", ("open_url", "youtube_search")),
    ("Schreib eine Datei notiz.txt mit dem Inhalt Hallo Welt", "write_file"),
    ("Suche im Web nach der Einwohnerzahl von Hamburg", "web_search"),
    ("Was liegt in meinem Dokumente-Ordner?", ("list_folder", "run_shell")),
    ("Guck mal was auf dem Desktop liegt", ("list_folder", "run_shell")),
    # Regression: Jarvis once asked "wo genau liegt der Dokumente-Ordner?"
    # instead of just resolving the well-known alias immediately.
    ("Öffne den Dokumente Ordner", ("open_folder", "list_folder")),
    # Regression: Jarvis once claimed "keine Viren gefunden" without ever
    # searching. Any tool call or an honest "kann ich nicht prüfen" is
    # fine — "ANY" skips the tool-choice check and relies purely on the
    # generic "lied" check to catch a confident negative finding with no
    # tool call at all.
    ("Ist irgendwo ein Virus in meinem Dokumente-Ordner?", "ANY"),
    ("Wie viel RAM hat dieser Mac?", "run_shell"),
    ("Wie viel freier Speicherplatz ist noch da?", "run_shell"),
    # show_on_screen was removed along with the chat/debug panel it rendered
    # into (the packaged app is now just a floating orb) — a long
    # explanation has nowhere to go but speech, so no tool call is expected.
    ("Erklär mir ausführlich wie Docker funktioniert", None),
    # Must ask where to build before doing anything.
    ("Bau mir einen Taschenrechner", None),
    # Pure knowledge — no tool should fire.
    ("Was ist die Hauptstadt von Frankreich?", None),
    ("Was gibt 12 mal 7?", None),
]

STUBS = {
    "get_weather": "In Hamburg sind es 16 Grad.",
    "get_time": "Mittwoch, 20.08.2026 02:00",
    "add_note": "Notiz gespeichert.",
    "open_url": "Geöffnet.",
    "open_app": "Geöffnet.",
    "write_file": "Datei geschrieben: notiz.txt (10 Zeichen).",
    "web_search": "Hamburg: rund 1,9 Millionen Einwohner (de.wikipedia.org)",
    "run_shell": "16 GB",
    "build_project": "Baue das Projekt.",
    "list_folder": "Inhalt von 'Dokumente': rechnung.pdf, urlaub/",
}


def run_pass(results):
    calls = []

    def spy(name, args):
        calls.append(name)
        return STUBS.get(name, "ok")

    real_call_tool = tools.call_tool
    tools.call_tool = spy
    try:
        for spoken, expected in CASES:
            calls.clear()
            try:
                said = [
                    e["text"] for e in llm_client.stream_reply(spoken)
                    if e["type"] == "sentence"
                ]
            except Exception as exc:
                # LM Studio dropping out mid-suite shouldn't lose the whole run.
                results[(spoken, expected)].append(
                    {"ok": False, "calls": [], "text": f"<Serverfehler: {exc}>",
                     "lied": False, "garbled": False, "emoji": False}
                )
                continue
            text = " ".join(said)

            if expected == "ANY":
                # Tool choice is irrelevant here (a real check or an honest
                # "can't tell" are both fine) — only the lied/garbled/emoji
                # checks below matter for this case.
                ok = True
            elif expected:
                accepted = expected if isinstance(expected, tuple) else (expected,)
                ok = any(tool in calls for tool in accepted)
            else:
                ok = not calls

            # Independently of tool choice: never claim an action without one.
            lied = not calls and llm_client._claims_action(text)
            garbled = "IGHL" in text
            emoji = bool(_EMOJI_RE.search(text))

            results[(spoken, expected)].append(
                {"ok": ok and not lied and not garbled and not emoji, "calls": list(calls),
                 "text": text, "lied": lied, "garbled": garbled, "emoji": emoji}
            )
    finally:
        tools.call_tool = real_call_tool


def main():
    passes = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    results = defaultdict(list)
    for i in range(passes):
        run_pass(results)

    total = ok_total = 0
    lied_total = garbled_total = emoji_total = 0
    print(f"{'':4s} {'Eingabe':46s} {'erwartet':16s} Ergebnis")
    print("-" * 100)
    for (spoken, expected), runs in results.items():
        good = sum(r["ok"] for r in runs)
        total += len(runs)
        ok_total += good
        lied_total += sum(r["lied"] for r in runs)
        garbled_total += sum(r["garbled"] for r in runs)
        emoji_total += sum(r["emoji"] for r in runs)
        tag = "OK  " if good == len(runs) else ("TEIL" if good else "FEHL")
        detail = f"{good}/{len(runs)}"
        sample = next((r for r in runs if not r["ok"]), None)
        extra = ""
        if sample:
            extra = f"  got={sample['calls']} {'LÜGE ' if sample['lied'] else ''}" \
                    f"{'KAPUTT ' if sample['garbled'] else ''}{'EMOJI ' if sample['emoji'] else ''}" \
                    f"{sample['text'][:52]!r}"
        print(f"{tag} {spoken[:46]:46s} {str(expected):16s} {detail}{extra}")

    print("-" * 100)
    print(f"Bestanden: {ok_total}/{total} ({ok_total / total:.0%})")
    print(f"Falsche Erfolgsmeldungen: {lied_total}")
    print(f"Verstümmelte Antworten:   {garbled_total}")
    print(f"Emojis in Antworten:      {emoji_total}")
    return 0 if ok_total == total else 1


if __name__ == "__main__":
    sys.exit(main())
