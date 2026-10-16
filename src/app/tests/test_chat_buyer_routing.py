"""Buying needs reach evidence gathering without requiring the word 'find'."""

import pytest

from app import chat, chatdata


@pytest.mark.parametrize("message", [
    "I need a laptop under 1000 euros",
    "I need a quiet laptop",
    "I want a laptop",
    "I want a device for less than $500",
    "I need something with a budget of 300 EUR",
    "I am looking for a quiet device",
    "Help me choose a laptop under 1000 euros",
    "Can you help me pick between these devices?",
    "1000 euro altı laptop arıyorum",
    "Bana 1000 euro altı laptop öner",
    "Hangi ürünü almalıyım?",
    "Bir cihaz satın almak istiyorum",
])
def test_a_buying_need_routes_to_research(message):
    assert chat.route_message(message) == "web"


@pytest.mark.parametrize("message", [
    "I need help with a Python error",
    "I need to understand gravity",
    "I need a Python script",
    "I want a short poem",
    "I need an explanation of gravity",
    "Can you explain a closure?",
    "Write a short poem about a robot",
    "How do I make a sourdough starter?",
    "Bir döngünün nasıl çalıştığını açıkla",
])
def test_ordinary_conversation_stays_direct(message):
    assert chat.route_message(message) == "chat"


@pytest.mark.parametrize("message", [
    "I need a laptop under 1000 euros from my saved checks",
    "Find a device in my catalogue",
    "Kaydettiğim ürünlerden birini öner",
    "Kataloğumdaki ürünler arasında hangisini almalıyım?",
])
def test_private_record_intent_takes_priority_over_buying_intent(message):
    assert chat.route_message(message) == "catalogue"


def test_budget_need_actually_reads_sources_before_answering():
    searched = []
    read = []
    prompts = []

    def search(query, limit):
        searched.append(query)
        return [{"title": "Product specification", "url": "https://maker.example/spec"}]

    def reader(url):
        read.append(url)
        return "The documented price is 800 euros. Availability needs checking."

    def ask(prompt):
        prompts.append(prompt)
        return "This page lists 800 euros. Availability remains unknown.\nSources: web_search"

    ctx = chatdata.Context(web_search=search, web_read=reader)
    out = chat.run_turn("I need a laptop under 1000 euros", ctx=ctx, ask=ask)

    assert searched == ["I need a laptop under 1000 euros"]
    assert read == ["https://maker.example/spec"]
    assert "The documented price is 800 euros" in prompts[0]
    assert out["sources"] == ["web_search", "https://maker.example/spec"]
    assert out["search_rounds"] == 1
