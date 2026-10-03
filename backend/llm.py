"""The Claude client: one helper for every request, plus usage counters for cost reporting."""
import collections
import sys
import threading

from backend import config

USAGE = collections.Counter()  # Claude usage in this process (tokens, calls, web searches), for cost reporting
USAGE_LOCK = threading.Lock()  # the corrective checks call Claude from two threads
LAST_WEB_SOURCES = []  # (title, url) of pages the last ask call's web searches returned


def ask(system, messages, max_tokens, stream, on_text=None, **kwargs):
    """One Claude request (resent while a server tool pauses the turn). With stream=True, text chunks go to
    on_text as they arrive (printed by default)."""
    import anthropic

    client = anthropic.Anthropic()
    on_text = on_text or (lambda t: print(t, end="", flush=True))
    LAST_WEB_SOURCES.clear()
    text = ""
    model = kwargs.pop("model", config.CLAUDE_MODEL)
    for _ in range(4):  # a server tool (web search) can pause a long turn: resend to let it continue
        args = dict(model=model, max_tokens=max_tokens, system=system, messages=messages, **kwargs)
        if not stream:
            reply = client.messages.create(**args)
        else:
            with client.messages.stream(**args) as s:
                for chunk in s.text_stream:
                    on_text(chunk)
                reply = s.get_final_message()
        text += "".join(b.text for b in reply.content if b.type == "text")  # skip thinking and tool blocks
        for b in reply.content:
            if b.type == "web_search_tool_result" and isinstance(b.content, list):
                LAST_WEB_SOURCES.extend((r.title, r.url) for r in b.content if (r.title, r.url) not in LAST_WEB_SOURCES)
        server = getattr(reply.usage, "server_tool_use", None)
        with USAGE_LOCK:
            USAGE.update(input=reply.usage.input_tokens, output=reply.usage.output_tokens, calls=1,
                         web_searches=getattr(server, "web_search_requests", 0) or 0)
        if reply.stop_reason != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": reply.content}]
    if stream:
        on_text("\n")
    if reply.stop_reason in ("max_tokens", "refusal"):
        print(f"[warning: answer stopped early ({reply.stop_reason})]", file=sys.stderr)
    return text
