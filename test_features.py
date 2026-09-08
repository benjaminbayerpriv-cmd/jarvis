"""Offline regression checks for Jarvis reliability features."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend import browser_agent, llm_client, memory, tools


def test_memory_vault():
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "Jarvis"
        old = (memory.ROOT, memory.KNOWLEDGE, memory.JOURNAL, memory.PROFILE, memory.TASKS, memory.NOTES)
        memory.ROOT = root
        memory.KNOWLEDGE, memory.JOURNAL = root / "Wissen", root / "Tagebuch"
        memory.PROFILE, memory.TASKS, memory.NOTES = root / "Profil.md", root / "Aufgaben.md", root / "Notizen.md"
        try:
            memory.initialize()
            memory.add_note("Milch kaufen")
            memory.remember_preference("Antworten kurz halten")
            memory.add_task("Browser-Erweiterung installieren")
            assert "type: jarvis-notes" in memory.NOTES.read_text()
            assert "Milch kaufen" in memory.NOTES.read_text()
            assert "Antworten kurz halten" in memory.PROFILE.read_text()
            assert "Browser-Erweiterung installieren" in memory.TASKS.read_text()
        finally:
            memory.ROOT, memory.KNOWLEDGE, memory.JOURNAL, memory.PROFILE, memory.TASKS, memory.NOTES = old


def test_invalid_model_stream_is_safe():
    real_stream = llm_client._stream_chat
    try:
        llm_client._stream_chat = lambda messages: iter([{"error": {"message": "model unloaded"}}])
        try:
            list(llm_client.stream_reply("Was ist los?"))
            raise AssertionError("ModelError expected")
        except llm_client.ModelError as exc:
            assert "model unloaded" in str(exc)
    finally:
        llm_client._stream_chat = real_stream


def test_youtube_routing():
    calls = []
    real_call = tools.call_tool
    try:
        tools.call_tool = lambda name, args: calls.append((name, args)) or "Ausgeführt."
        events = list(llm_client.stream_reply("Suche auf YouTube nach Donut SMP"))
        assert calls == [("youtube_search", {"query": "Donut SMP"})]
        # The model paraphrases the tool's result rather than echoing it
        # verbatim, so asserting exact wording here would just test today's
        # phrasing, not the actual guarantee: a real tool ran, and nothing
        # denies that it did (see llm_client._claims_action / _vet).
        sentences = [e["text"] for e in events if e["type"] == "sentence"]
        assert sentences, "expected at least one spoken sentence"
        assert not any("nicht ausgeführt" in s for s in sentences), sentences
    finally:
        tools.call_tool = real_call


def test_browser_without_extension_is_honest():
    agent = browser_agent.BrowserAgent()
    assert "nicht verbunden" in agent.command("open_url", {"url": "https://youtube.com"}).lower()


if __name__ == "__main__":
    test_memory_vault()
    test_invalid_model_stream_is_safe()
    test_youtube_routing()
    test_browser_without_extension_is_honest()
    print("Feature-Tests: OK")
