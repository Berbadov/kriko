"""Tests for packs/cars/pipeline/sources/tiers.py — source tier resolution."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from packs.cars.pipeline.sources.tiers import domain_from_url, resolve_tier, trust_of


class TestResolveTier:
    def test_explicit_specialist(self):
        tier, trust = resolve_tier("asrgearboxrepairs.co.uk")
        assert tier == "specialist"
        assert 0 < trust < 1

    def test_explicit_authoritative(self):
        assert resolve_tier("user-manual.renault.com")[0] == "authoritative"

    def test_subdomain_reduces_to_registrable(self):
        # Listed at registrable level -> matches even with a subdomain host.
        assert resolve_tier("www.whatcar.com")[0] == "enthusiast"
        # Listed verbatim with subdomain -> verbatim match wins.
        assert resolve_tier("en.mercedesassistance.com")[0] == "seo_blog"

    def test_full_url_accepted(self):
        tier, trust = resolve_tier("https://www.asrgearboxrepairs.co.uk/7-speed-dct-renault/")
        assert tier == "specialist"
        assert trust == 0.75

    def test_unknown_domain_falls_back_to_default(self):
        reg_default = "seo_blog"
        tier, trust = resolve_tier("totally-unknown-site.example")
        assert tier == reg_default
        assert trust == 0.20

    def test_forum_rule(self):
        assert resolve_tier("forum.somesite.org")[0] == "forum_ugc"

    def test_empty_and_none(self):
        assert resolve_tier(None)[0] == "seo_blog"
        assert resolve_tier("")[0] == "seo_blog"

    def test_trust_of_matches_resolve(self):
        assert trust_of("dsgservisi.com") == resolve_tier("dsgservisi.com")[1]


class TestDomainFromUrl:
    def test_https(self):
        assert domain_from_url("https://example.com/path?x=1") == "example.com"

    def test_port_stripped(self):
        assert domain_from_url("http://example.com:8080/x") == "example.com"

    def test_garbage(self):
        assert domain_from_url("") == ""
        assert domain_from_url(None) == ""
