"""Behaviour harness for Jarvis.

Measures the thing that actually matters: given a spoken sentence, does the
right tool really run, and does Jarvis avoid claiming it did something it
didn't? Tool side effects are stubbed so the suite can run repeatedly
without opening apps or typing into windows.

    python3 test_jarvis.py            # one pass
    python3 test_jarvis.py 3          # three passes, for flaky behaviour
"""

import sys
from collections import defaultdict

from backend import llm_client, tools

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
    ("Was siehst du gerade?", "look_at_display"),
    ("Was zeigt mein Screen gerade an?", "look_at_display"),
    ("Mach einen Screenshot", "save_screenshot"),
    ("Mach ein Bildschirmfoto und speicher es auf dem Desktop", "save_screenshot"),
    ("Tippe Hallo Welt", "type_text"),
    ("Schreib den Text Guten Morgen", "type_text"),
    ("Drück mal Enter", "press_key"),
    ("Drücke cmd s zum Speichern", "press_key"),
    ("Klick auf das Suchfeld", "click_on_screen"),
    ("Wie viel RAM hat dieser Mac?", "run_shell"),
    ("Wie viel freier Speicherplatz ist noch da?", "run_shell"),
    ("Erklär mir ausführlich wie Docker funktioniert", "show_on_screen"),
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
    "look_at_display": "Ein Fenster mit Code.",
    "save_screenshot": "Screenshot gespeichert unter /Users/x/Desktop/foo.png.",
    "type_text": "Getippt: Hallo Welt",
    "press_key": "Taste gedrückt: enter",
    "click_on_screen": "Angeklickt.",
    "run_shell": "16 GB",
    "show_on_screen": "Angezeigt.",
    "mouse_action": "Ok.",
    "build_project": "Baue das Projekt.",
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
                     "lied": False, "garbled": False}
                )
                continue
            text = " ".join(said)

            if expected:
                ok = expected in calls
            else:
                ok = not calls

            # Independently of tool choice: never claim an action without one.
            lied = not calls and llm_client._claims_action(text)
            garbled = "IGHL" in text

            results[(spoken, expected)].append(
                {"ok": ok and not lied and not garbled, "calls": list(calls),
                 "text": text, "lied": lied, "garbled": garbled}
            )
    finally:
        tools.call_tool = real_call_tool


def main():
    passes = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    results = defaultdict(list)
    for i in range(passes):
        run_pass(results)

    total = ok_total = 0
    lied_total = garbled_total = 0
    print(f"{'':4s} {'Eingabe':46s} {'erwartet':16s} Ergebnis")
    print("-" * 100)
    for (spoken, expected), runs in results.items():
        good = sum(r["ok"] for r in runs)
        total += len(runs)
        ok_total += good
        lied_total += sum(r["lied"] for r in runs)
        garbled_total += sum(r["garbled"] for r in runs)
        tag = "OK  " if good == len(runs) else ("TEIL" if good else "FEHL")
        detail = f"{good}/{len(runs)}"
        sample = next((r for r in runs if not r["ok"]), None)
        extra = ""
        if sample:
            extra = f"  got={sample['calls']} {'LÜGE ' if sample['lied'] else ''}" \
                    f"{'KAPUTT ' if sample['garbled'] else ''}{sample['text'][:52]!r}"
        print(f"{tag} {spoken[:46]:46s} {str(expected):16s} {detail}{extra}")

    print("-" * 100)
    print(f"Bestanden: {ok_total}/{total} ({ok_total / total:.0%})")
    print(f"Falsche Erfolgsmeldungen: {lied_total}")
    print(f"Verstümmelte Antworten:   {garbled_total}")
    return 0 if ok_total == total else 1


if __name__ == "__main__":
    sys.exit(main())
