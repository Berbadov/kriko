"""Buying needs reach evidence gathering without requiring the word 'find'."""

import pytest

from app import chat, chatdata, exactfind


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

    # The first search found no trusted shop, so one query limited to popular
    # shops follows it. Both stubs return the same page, which is read once.
    assert searched[0] == "I need a laptop under 1000 euros"
    assert len(searched) == 2 and "site:" in searched[1]
    assert read == ["https://maker.example/spec"]
    assert "The documented price is 800 euros" in prompts[0]
    assert out["sources"] == ["web_search", "https://maker.example/spec"]
    assert out["search_rounds"] == 1


@pytest.mark.parametrize("message", [
    "Megane 4 1.5 blue dci 2020 model icin yag ve filtre seti",
    "Golf 7 1.6 tdi 2016 brake pads",
    "iPhone 15 Pro case 6.1 inch",
])
def test_a_product_named_without_a_verb_is_a_buying_request(message):
    assert chat.route_message(message) == "web"


@pytest.mark.parametrize("message", [
    "Which engine oil and filters should I use for a 2020 Renault Megane IV 1.5 Blue dCi?",
    "2020 Renault Megane IV Sedan 1.5 Blue dCi için hangi motor yağını kullanmalıyım?",
    "2020 Renault Megane IV 1.5 Blue dCi icin hangi motor yagini kullanmaliyim?",
    "Hangi yağ 2020 Renault Megane 1.5 Blue dCi için uygundur?",
    "Hangi yag 2020 Renault Megane 1.5 Blue dCi icin uygundur?",
    "2020 Renault Megane IV 1.5 Blue dCi için yağ ve filtre önerir misin?",
])
def test_product_fitment_advice_routes_to_live_shopping_search(message):
    assert not exactfind.is_purchase_request(message)
    assert chat.route_message(message) == "web"
    assert chat._buying_request(message)


@pytest.mark.parametrize("message", [
    "What is 2 + 2 in binary",
    "Explain how TCP handshakes work in 3 steps",
    "Write a python function that sums 3 numbers",
    "Why did Rome fall in 476?",
])
def test_a_question_or_a_task_with_a_number_stays_chat(message):
    assert chat.route_message(message) == "chat"


@pytest.mark.parametrize("message", [
    "What is the latest model specification?",
    "Find the official manual for the latest model specification",
])
def test_a_factual_product_question_uses_web_without_shopping_fanout(message):
    assert chat.route_message(message) == "web"
    assert not chat._buying_request(message)
