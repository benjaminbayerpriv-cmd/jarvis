"""Speech output, with fallbacks that keep Jarvis talking.

Supertonic is the primary voice: a local, offline, unlimited neural TTS
model that sounds far better than the old OS-builtin voice ever did, with
no per-character cost or quota. If it can't load (e.g. first run with no
internet to fetch the model), this falls back to ElevenLabs when a key is
configured (free tier is 10k characters a month and runs dry without
warning), and finally to the voice built into the operating system — worse
sounding, but free, offline and always available: macOS's built-in `say`,
the SAPI synthesizer (via PowerShell, no extra dependency needed) on
Windows. Silence is the one outcome that makes Jarvis look broken.
"""

from __future__ import annotations

import io
import platform
import re
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np
import requests
from num2words import num2words
from supertonic import TTS

from . import config, platform_utils

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

MACOS_VOICE = "Anna"

IS_WINDOWS = platform.system() == "Windows"

# Set once ElevenLabs reports quota exhaustion, so we stop paying the
# latency of a doomed request on every single sentence.
_elevenlabs_blocked = False

# Supertonic loads a model from disk (slow-ish), so it's built once, lazily,
# and reused for every request rather than per-call.
_supertonic_lock = threading.Lock()
_supertonic_tts: TTS | None = None
_supertonic_style = None

# File extension + mime type produced by each engine, so callers (the /tts
# route, the filler cache) don't need their own platform checks.
ENGINE_MEDIA = {
    "supertonic": ("wav", "audio/wav"),
    "elevenlabs": ("mp3", "audio/mpeg"),
    "macos": ("m4a", "audio/mp4"),
    "windows": ("wav", "audio/wav"),
}


class VoiceInfo:
    """Which engine produced the last clip, for the UI to mention."""

    engine = "elevenlabs"


def _macos_say(text: str) -> bytes:
    out = Path(tempfile.mkdtemp()) / "say.m4a"
    subprocess.run(
        ["say", "-v", MACOS_VOICE, "--file-format=m4af", "--data-format=aac",
         "-o", str(out), text],
        check=True,
        capture_output=True,
        timeout=60,
    )
    data = out.read_bytes()
    try:
        out.unlink()
        out.parent.rmdir()
    except OSError:
        pass
    return data


def _windows_say(text: str) -> bytes:
    """Render text via the SAPI synthesizer built into Windows. The text is
    piped over stdin (rather than interpolated into the script) so quotes
    and special characters in it can't break out of the PowerShell command."""
    out = Path(tempfile.mkdtemp()) / "say.wav"
    script = (
        # Without this, PowerShell reads stdin using the console's
        # codepage (cp1252 on German Windows) regardless of what encoding
        # Python used to write it below — mismatched, every ü/ö/ä/ß in the
        # spoken text would come out corrupted rather than just failing.
        "[Console]::InputEncoding = [System.Text.Encoding]::UTF8; "
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{out}'); "
        "$s.Speak([Console]::In.ReadToEnd()); "
        "$s.Dispose()"
    )
    subprocess.run(
        platform_utils.powershell(script),
        input=text,
        check=True,
        capture_output=True,
        text=True,
        # Matches [Console]::InputEncoding above; without an explicit
        # encoding here, text=True encodes `input` using the OS locale's
        # preferred codepage, not UTF-8 — this is the last-resort voice
        # (Supertonic and ElevenLabs both already failed to get here), so
        # a crash on an unencodable character means total silence, the one
        # outcome this whole module exists to avoid.
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    data = out.read_bytes()
    try:
        out.unlink()
        out.parent.rmdir()
    except OSError:
        pass
    return data


# Neither Supertonic nor the OS voices do any real number normalization —
# they feed digits straight to the model's grapheme frontend, which reads
# anything beyond a couple of digits one character at a time instead of as
# a number ("eins-zwei-drei-vier..." instead of "eintausendzweihundert-
# vierunddreißig"). ElevenLabs' API already handles this well on its own,
# so this is only applied to the two engines that don't.
#
# Clock times ("14:30") used to be left alone on the assumption that they
# already read fine digit-by-digit in German — true for ElevenLabs, but
# Supertonic's frontend doesn't silently skip the colon: it reads it aloud
# as the literal word "Doppelpunkt" ("vierzehn Uhr Doppelpunkt dreißig"
# instead of "vierzehn Uhr dreißig"), observed live as the exact cause of
# choppy-sounding time replies. Given its own expansion below (_spell_time)
# instead. Math symbols get the same treatment for the same reason —
# Supertonic's own normalizer either drops "/" silently or passes
# "+ - * = %" straight through unpronounced.
# The trailing "(?:\s*Uhr)?" absorbs a literal "Uhr" the model already
# wrote right after the digits ("20:44 Uhr", the common phrasing) so
# _spell_time's own "Uhr" doesn't end up doubled ("zwanzig Uhr
# vierundvierzig Uhr") — works the same either way if it wasn't there.
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b(?:\s*Uhr)?")


def _spell_time(match: re.Match) -> str:
    hour, minute, second = match.group(1), match.group(2), match.group(3)
    words = f"{num2words(int(hour), lang='de')} Uhr"
    # "zwanzig Uhr null" for :00 sounds robotic — natural German just says
    # "zwanzig Uhr" and drops the minute entirely, same as clock speech
    # normally works, and num2words(0) would emit an actual "null" here.
    if int(minute) != 0:
        words += f" {num2words(int(minute), lang='de')}"
    if second is not None and int(second) != 0:
        words += f" und {num2words(int(second), lang='de')} Sekunden"
    return words
_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b")
# The two extra lookarounds (before/after) keep this off a dotted token
# that isn't actually German thousands-grouping, like a version number
# ("3.11") — without them, the grouped-thousands alternative fails (its
# groups must be exactly 3 digits), the plain \d+ alternative matches "3"
# and "11" as two separate numbers instead, and the result reads as
# "drei.elf" with the bare dot still sitting in between.
_NUMBER_RE = re.compile(r"(?<!\d\.)(?<!\w)(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?(?!\w)(?!\.\d)")

_MONTH_NAMES = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
}

# The model doesn't only write dates numerically ("07.09.2026") — writing
# the day as "21. Januar 2025" (month spelled out, not a second number) is
# just as common in natural German text, and _DATE_RE above doesn't match
# it at all (it needs a numeric month). Left unhandled, that "21." falls
# straight through to the plain cardinal-number pass below, which drops
# the trailing dot's ordinal meaning entirely — observed live, exactly
# this: "einundzwanzig. Januar" instead of "einundzwanzigste Januar".
_DATE_WORDS_RE = re.compile(
    r"\b(\d{1,2})\.\s*("
    + "|".join(_MONTH_NAMES.values())
    + r")\b(?:\s+(\d{4}))?"
)


def _spell_date_words(match: re.Match) -> str:
    day = int(match.group(1))
    month_name = match.group(2)
    year = match.group(3)
    if not 1 <= day <= 31:
        return match.group(0)
    day_words = num2words(day, lang="de", to="ordinal")
    result = f"{day_words} {month_name}"
    if year:
        result += f" {num2words(int(year), lang='de')}"
    return result

_MATH_SYMBOL_PATTERNS = [
    (re.compile(r"(?<=\d)\s*\+\s*(?=\d)"), " plus "),
    (re.compile(r"\+(?=\d)"), "plus "),
    (re.compile(r"(?<=\d)\s*-\s*(?=\d)"), " minus "),
    (re.compile(r"(?<![\w.,])-(?=\d)"), "minus "),
    (re.compile(r"(?<=\d)\s*[*xX]\s*(?=\d)"), " mal "),
    (re.compile(r"(?<=\d)\s*/\s*(?=\d)"), " durch "),
    (re.compile(r"(?<=\d)\s*=\s*(?=\d)"), " gleich "),
    (re.compile(r"(?<=\d)\s*%"), " Prozent"),
]


def _expand_math_symbols_for_speech(text: str) -> str:
    for pattern, replacement in _MATH_SYMBOL_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _spell_date(match: re.Match) -> str:
    day, month, year = (int(g) for g in match.groups())
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return match.group(0)  # not actually a date (e.g. a version number)
    day_words = num2words(day, lang="de", to="ordinal")
    month_name = _MONTH_NAMES[month]
    year_words = num2words(year, lang="de")
    return f"{day_words} {month_name} {year_words}"


def _spell_number(match: re.Match) -> str:
    integer_part = match.group(1).replace(".", "")
    fraction = match.group(2)
    try:
        words = num2words(int(integer_part), lang="de")
    except (ValueError, OverflowError):
        return match.group(0)
    if fraction:
        digit_words = " ".join(num2words(int(d), lang="de") for d in fraction)
        words += f" Komma {digit_words}"
    return words


# Two or more bare digit groups separated only by single spaces, with
# nothing else marking them as one quantity (no thousands dot, no math
# symbol) — read naturally as one gigantic cardinal number otherwise.
# Observed: "030 1234567" (a plain phone number split into area code and
# local number) turned into "dreißig eine Million
# zweihundertvierunddreißigtausendfünfhundertsiebenundsechzig" instead of
# being read digit by digit. Short runs (a couple of small numbers just
# mentioned next to each other, e.g. "8 12") are left alone — under six
# total digits reads fine as separate cardinal numbers via the normal pass
# below, and is far more likely to be two unrelated numbers than a phone
# number fragment.
_DIGIT_GROUPS_RE = re.compile(r"(?<!\w)\d{1,15}(?: \d{1,15}){1,}(?!\w)")


def _spell_digit_groups(match: re.Match) -> str:
    digits = match.group(0).replace(" ", "")
    if len(digits) < 6:
        return match.group(0)
    return " ".join(num2words(int(d), lang="de") for d in digits)



def _expand_numbers_for_speech(text: str) -> str:
    # Every step below replaces digits with words, so none of them can be
    # re-matched (and re-mangled) by a later step in the pipeline — no
    # shielding/placeholder juggling needed, unlike when _TIME_RE used to
    # just protect its match verbatim instead of actually expanding it.
    expanded = _TIME_RE.sub(_spell_time, text)
    expanded = _DATE_RE.sub(_spell_date, expanded)
    expanded = _DATE_WORDS_RE.sub(_spell_date_words, expanded)
    # Phone-number-shaped runs before the math pass — after conversion the
    # result is words, not digits, so it can't be re-matched by _NUMBER_RE
    # below either way.
    expanded = _DIGIT_GROUPS_RE.sub(_spell_digit_groups, expanded)
    # Math symbols expand to words before numbers do, so e.g. "12+34"
    # becomes "12 plus 34" first — still cleanly digit-bounded for
    # _NUMBER_RE right after, since "plus"/"minus"/etc. are word characters
    # that its (?<!\w)/(?!\w) boundaries respect either way.
    expanded = _expand_math_symbols_for_speech(expanded)
    return _NUMBER_RE.sub(_spell_number, expanded)


def _local_say(text: str) -> bytes:
    text = _expand_numbers_for_speech(text)
    if IS_WINDOWS:
        VoiceInfo.engine = "windows"
        return _windows_say(text)
    VoiceInfo.engine = "macos"
    return _macos_say(text)


def _elevenlabs(text: str) -> bytes:
    url = ELEVENLABS_URL.format(voice_id=config.ELEVENLABS_VOICE_ID)
    resp = requests.post(
        url,
        headers={
            "xi-api-key": config.ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        json={
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.65,
                "similarity_boost": 0.75,
                "speed": 0.9,
            },
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content


def _get_supertonic() -> tuple[TTS, object]:
    """Load the Supertonic model and voice style once, then reuse them.
    Thread-safe since FastAPI's sync endpoints run each request in a
    worker thread."""
    global _supertonic_tts, _supertonic_style
    if _supertonic_tts is None:
        with _supertonic_lock:
            if _supertonic_tts is None:
                tts = TTS(auto_download=True)
                _supertonic_style = tts.get_voice_style(voice_name=config.SUPERTONIC_VOICE)
                _supertonic_tts = tts
    return _supertonic_tts, _supertonic_style


def _sanitize_for_supertonic(text: str, tts: TTS) -> str:
    """Drop any character outside Supertonic's ~8000-character supported
    set instead of letting synthesize() raise ValueError over it.

    Observed live: a lone U+FFFD replacement character appearing mid-word
    in ordinary German text, which crashed Supertonic entirely for that
    whole reply and cascaded into ElevenLabs (also broken — no real key
    configured) and finally the noticeably worse Windows SAPI voice. Most
    plausible source is upstream: LM Studio's streaming token output can
    split a multi-byte UTF-8 character (ü/ö/ä/ß are all multi-byte) across
    two token chunks, and if the inference server decodes each chunk's
    bytes independently rather than buffering incomplete sequences, the
    orphaned half becomes U+FFFD before it ever reaches us. Nothing on
    this end can fix that at the source, but one garbled character
    shouldn't take down the whole sentence's voice quality — stripping it
    keeps everything else intact instead.
    """
    is_valid, unsupported = tts.model.text_processor.validate_text(text)
    if not is_valid:
        print(f"[tts] Entferne nicht unterstützte Zeichen vor der Synthese: {unsupported}")
        for ch in unsupported:
            text = text.replace(ch, "")
    return text


def _supertonic_say(text: str) -> bytes:
    text = _expand_numbers_for_speech(text)
    tts, style = _get_supertonic()
    text = _sanitize_for_supertonic(text, tts)
    # FastAPI runs sync endpoints in a thread pool, and it's undocumented
    # whether one Supertonic engine tolerates concurrent synthesize() calls
    # from different threads — e.g. the startup filler-generation pass
    # overlapping a live chat reply. Observed live: intermittent silent
    # failures here that fell through to the macOS voice. Serializing every
    # call through the one shared engine costs nothing perceptible (each
    # call is already sub-second) and removes the race entirely.
    with _supertonic_lock:
        wav, _duration = tts.synthesize(text=text, lang=config.SUPERTONIC_LANG, voice_style=style)
    samples = np.clip(np.asarray(wav).squeeze(), -1.0, 1.0)
    pcm16 = (samples * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(tts.sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def synthesize(text: str) -> bytes:
    """Return spoken audio for `text`. Never raises for ordinary failures —
    silence is the one outcome that makes Jarvis look broken."""
    global _elevenlabs_blocked

    try:
        audio = _supertonic_say(text)
        VoiceInfo.engine = "supertonic"
        return audio
    except Exception as exc:  # noqa: BLE001 - fall through to ElevenLabs/OS
        print(f"[tts] Supertonic nicht verfügbar, nutze Ausweich-Stimme: {exc}")

    if config.ELEVENLABS_API_KEY and not _elevenlabs_blocked:
        try:
            audio = _elevenlabs(text)
            VoiceInfo.engine = "elevenlabs"
            return audio
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            body = (exc.response.text if exc.response is not None else "")[:200]
            # 401 = bad key, 429 = rate limited. Quota exhaustion arrives as
            # a 401 with quota_exceeded in the body.
            if status in (401, 402, 429) or "quota" in body.lower():
                _elevenlabs_blocked = True
                print(f"[tts] ElevenLabs nicht verfügbar ({status}), nutze lokale Stimme. {body}")
        except requests.RequestException as exc:
            print(f"[tts] ElevenLabs Netzwerkfehler, nutze lokale Stimme: {exc}")

    return _local_say(text)
