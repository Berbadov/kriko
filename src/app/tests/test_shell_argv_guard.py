"""A `.cmd` harness runs through `cmd.exe`, so its argv is not just text.

The model and effort names are the reader's own free text, written from
Settings, and they travel in this argv. `list2cmdline` — which Python uses to
build the command line for `shell=True` — quotes an argument only when it
contains whitespace or a quote, so `x&calc` as a model name reached `cmd.exe`
bare and `&` was a command separator: argv-level injection into `%ComSpec% /c`.

The tests below pin both halves of the rule, because the obvious version of it
is wrong: refusing `&` in *every* argument would refuse every research brief,
which is one quoted argument full of prose.
"""

import pytest

from app.providers.harness import HarnessResearcher

BRIEF = ("Find what goes wrong with this product. Owners say the hinge & the "
         "latch both wear; about 50% report it within two years.")


def check(*arguments):
    return HarnessResearcher._refuse_shell_injection(["C:\\npm\\claude.cmd", *arguments])


def test_a_bare_argument_with_shell_syntax_is_refused():
    with pytest.raises(RuntimeError, match="cmd.exe reads as syntax"):
        check("x&calc")


@pytest.mark.parametrize("value", ["a|b", "a>b", "a<b", "a^b", "a\r\nb"])
def test_every_separator_is_refused_when_it_reaches_cmd_bare(value):
    with pytest.raises(RuntimeError):
        check(value)


def test_an_ordinary_model_name_is_fine():
    check("sonnet", "--effort", "high", "claude-sonnet-4-5")


def test_a_quoted_brief_may_contain_ampersands_and_lone_percent():
    """It has spaces, so `list2cmdline` quotes it and `cmd.exe` leaves it alone."""
    check("--model", "sonnet", BRIEF)


def test_a_variable_reference_is_refused_even_inside_quotes():
    """`cmd.exe` expands `%NAME%` inside double quotes; quoting is not enough."""
    with pytest.raises(RuntimeError, match=r"%PATH%"):
        check("--model", "sonnet %PATH%")


def test_a_bare_variable_reference_is_refused_too():
    with pytest.raises(RuntimeError):
        check("%COMSPEC%")
