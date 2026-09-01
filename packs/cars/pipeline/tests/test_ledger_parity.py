import yaml
from packs.cars.pipeline.ledger import parity


def test_compare_reports_matched_and_missing(tmp_path):
    old = tmp_path / "old"; old.mkdir()
    new = tmp_path / "new"; new.mkdir()
    # existing backend part files are a dict with a `claims:` list; the ledger
    # export is a bare list — _load must read both (dict shape covered here).
    (old / "dq381.yaml").write_text(yaml.dump({
        "part_id": "dq381", "part_type": "transmission",
        "claims": [
            {"title": "DQ381 mechatronic solenoid wear", "domain": "transmission"},
            {"title": "DQ200 hydraulic pressure failure", "domain": "transmission"},
        ],
    }))
    (new / "dq381.yaml").write_text(yaml.dump([
        {"title": "Mechatronic solenoid wear on DQ381", "domain": "transmission"},
    ]))
    report = parity.compare([old], new)
    assert "matched: 1" in report
    assert "DQ200 hydraulic pressure failure" in report  # only-in-existing, listed


def test_shared_source_url_matches_rewritten_titles(tmp_path):
    """Backlog B1 blocker 2: the verdict stage rewrites titles, so title
    Jaccard matched nothing. A shared source URL is the stable identity."""
    old = tmp_path / "old"; old.mkdir()
    new = tmp_path / "new"; new.mkdir()
    (old / "dq200.yaml").write_text(yaml.dump({"claims": [
        {"title": "Premature clutch pack wear in urban driving",
         "domain": "transmission",
         "sources": [{"source_url": "https://aboutthecars.com/vw/dq200/",
                      "quote": "clutch wear"}]},
    ]}))
    (new / "dq200.yaml").write_text(yaml.dump([
        {"title": "Dry clutch packs wear out early in stop-and-go traffic",
         "domain": "transmission",
         "sources": [{"source_url": "https://aboutthecars.com/vw/dq200",
                      "quote": "clutch wear"}]},
    ]))
    report = parity.compare([old], new)
    assert "matched: 1" in report
    assert "only in existing YAML (0)" in report


def test_url_match_requires_domain_agreement(tmp_path):
    """One 'Golf 7 problems' page seeds many distinct claims. A legacy ENGINE
    claim and an exported TRANSMISSION claim from the same URL are NOT the
    same claim — the URL identity only holds within the same domain."""
    old = tmp_path / "old"; old.mkdir()
    new = tmp_path / "new"; new.mkdir()
    (old / "golf7_body.yaml").write_text(yaml.dump({"claims": [
        {"title": "Timing Chain Tensioner Failures (EA888 Gen 3)",
         "domain": "engine",
         "sources": [{"source_url": "https://x.test/golf7-problems",
                      "quote": "chain stretch"}]},
    ]}))
    (new / "dq200.yaml").write_text(yaml.dump([
        {"title": "Mechatronic unit failure",
         "domain": "transmission",
         "sources": [{"source_url": "https://x.test/golf7-problems",
                      "quote": "mechatronic"}]},
    ]))
    report = parity.compare([old], new)
    assert "matched: 0" in report
    assert "only in existing YAML (1)" in report
    assert "only in ledger export (1)" in report


def test_moved_claim_reported_as_move_not_loss(tmp_path):
    """A DQ200 claim misfiled under dq381.yaml and rerouted to dq200.yaml is an
    explainable improvement — reported as a move, not an only-old loss."""
    old = tmp_path / "old"; old.mkdir()
    new = tmp_path / "new"; new.mkdir()
    (old / "dq381.yaml").write_text(yaml.dump({"claims": [
        {"title": "DQ200 hydraulic pressure failure",
         "domain": "transmission",
         "sources": [{"source_url": "https://x.test/dsg-comparison",
                      "quote": "dq200 pressure"}]},
    ]}))
    (new / "dq200.yaml").write_text(yaml.dump([
        {"title": "Hydraulic pressure circuit failure",
         "domain": "transmission",
         "sources": [{"source_url": "https://x.test/dsg-comparison",
                      "quote": "dq200 pressure"}]},
    ]))
    report = parity.compare([old], new)
    assert "matched: 0" in report
    assert "[dq381 -> dq200] DQ200 hydraulic pressure failure" in report
    assert "only in existing YAML (0)" in report
    assert "only in ledger export (0)" in report
