import os
import tempfile
from pathlib import Path

import app
import store

theses = [
    {"id": 1, "title": "Open", "supervisor": "A", "available": True, "description": "x" * 500 + "TAIL"},
    {"id": 2, "title": "Closed", "supervisor": "B", "available": False, "description": "closed text"},
]

prompt = app.system_prompt(theses, {"bio": "likes AI"}, None, False)
assert "[1] Open" in prompt and "likes AI" in prompt
assert "Closed" not in prompt and "TAIL" not in prompt and "web_search" not in prompt
assert "TAIL" in app.system_prompt(theses, {}, 1, True)

assert app.tool_summary("web_search", {"results": [{"title": "T", "url": "https://u.gr"}]}) == "- [T](https://u.gr)"
assert app.tool_summary("web_fetch", {"title": "P", "content": "body"}) == "**P**\n\nbody"
assert app.tool_input({"function": {"name": "web_search", "arguments": "{}"}}) == ("web_search", None)

os.environ.update(LLM_PROVIDER="ollama", LLM_API_KEY="key", LLM_MODEL="model")
calls, events = [], []


def fake_post(url, body, key):
    calls.append((url, body))
    if url.endswith("/web_search"):
        return {"results": [{"title": "t", "url": "https://t.gr"}]}
    if len(calls) == 1:
        call = {"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": '{"query": "q"}'}}
        return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}]}
    return {"choices": [{"message": {"role": "assistant", "content": "done"}}]}


app.post_json = fake_post
reply, steps = app.chat([{"role": "user", "content": "hi"}], {}, None, theses, events.append)
assert reply == "done"
assert steps == [{"name": "web_search", "input": "q", "output": "- [t](https://t.gr)"}]
assert [event["type"] for event in events] == ["tool", "tool_done"]
assert "tools" in calls[0][1]
assert calls[1] == ("https://ollama.com/api/web_search", {"query": "q"})
assert calls[2][1]["messages"][-1]["tool_call_id"] == "c1"

with tempfile.TemporaryDirectory() as directory:
    store.DB_PATH = Path(directory) / "test.db"
    store.init()
    assert store.load_profile()["liked_professors"] == []
    assert store.clean_profile({"bio": 5}) is None
    store.save_profile(store.clean_profile({"bio": "AI", "liked_professors": ["A"]}))
    assert store.load_profile()["bio"] == "AI"

    chat = store.save_exchange(None, "  first   question ", 1, "answer", steps)
    assert chat["title"] == "first question"
    store.save_exchange(chat["id"], "second", None, "answer 2", [])
    saved = store.get_chat(chat["id"])
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant", "user", "assistant"]
    assert saved["messages"][0]["focus_id"] == 1 and saved["messages"][1]["steps"] == steps
    assert store.list_chats()[0]["id"] == chat["id"]
    assert store.delete_chat(chat["id"]) and store.get_chat(chat["id"]) is None
    assert store.save_exchange(chat["id"], "late", None, "reply", []) is None
print("ok")
