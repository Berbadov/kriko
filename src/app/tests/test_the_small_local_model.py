"""A small model that thinks first still answers, and what it quotes is readable.

A reader's friend ran Qwen 3.5 0.8B through Ollama: the model spent the whole
reply budget on its reasoning, `content` came back empty, and the run failed.
Asked not to think it answers the same prompt in under a second.
"""

from app.providers import pagereader
from app.providers.local_inference import OpenAICompatSocket


def _socket(**kwargs):
    sent = []
    one = OpenAICompatSocket("http://127.0.0.1:11434", "qwen3.5:0.8b", **kwargs)

    def post(body):
        sent.append(dict(body))
        return {"choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}], "usage": {}}

    one._post = post
    return one, sent


def test_thinking_is_off_unless_the_reader_chose_an_effort():
    one, sent = _socket()
    one.complete("hi")
    assert sent[0]["reasoning_effort"] == "none"


def test_a_chosen_effort_wins():
    one, sent = _socket(reasoning_effort="high")
    one.complete("hi")
    assert sent[0]["reasoning_effort"] == "high"


def test_utf8_decoded_as_windows_1252_is_repaired_line_by_line():
    broken = "triggerâ€”it runs\ncafÃ© au lait"
    assert pagereader.unmangle(broken) == "trigger—it runs\ncafé au lait"


def test_honest_text_is_left_alone():
    honest = "café — and a real Ã in a name\nsecond line"
    assert pagereader.unmangle(honest) == honest


def test_one_bad_line_does_not_cost_the_good_ones():
    text = "fine é\nÃA stays\ntriggerâ€”it"
    got = pagereader.unmangle(text).splitlines()
    assert got == ["fine é", "ÃA stays", "trigger—it"]
