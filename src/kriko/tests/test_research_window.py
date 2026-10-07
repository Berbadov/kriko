"""`focus`: the window a model reads is the page's part about the subject."""

from kriko.research.window import GAP, focus


def test_a_text_that_fits_is_returned_unchanged():
    assert focus("short text", 100, ["anything"]) == "short text"


def test_no_terms_is_the_plain_head():
    text = "x" * 50 + "\n\n" + "y" * 50
    assert focus(text, 40) == text[:40]


def test_the_blocks_naming_the_terms_come_before_the_menu():
    filler = "\n\n".join(f"Link {i} somewhere else" for i in range(300))
    text = f"The page title\n\n{filler}\n\nThe pump seal leaks after a winter."
    window = focus(text, 600, ["pump seal leaks"])
    assert len(window) <= 600
    assert window.startswith("The page title")
    assert "The pump seal leaks after a winter." in window
    assert GAP in window


def test_the_kept_blocks_stay_in_the_pages_order():
    blocks = ["Title", "first about the pump", *["noise"] * 200, "second about the pump"]
    window = focus("\n\n".join(blocks), 300, ["pump"])
    assert window.index("first about") < window.index("second about")


def test_every_kept_block_is_a_verbatim_part_of_the_page():
    """Grounding depends on it: a quote from the window is on the page."""
    text = "\n\n".join(f"Block {i} mentions the valve {i % 7} times" for i in range(500))
    window = focus(text, 2000, ["valve"])
    for part in window.split(GAP):
        for block in part.split("\n\n"):
            assert block in text
