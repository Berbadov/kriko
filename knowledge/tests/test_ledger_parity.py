import yaml
from knowledge.ledger import parity


def test_compare_reports_matched_and_missing(tmp_path):
    old = tmp_path / "old"; old.mkdir()
    new = tmp_path / "new"; new.mkdir()
    (old / "dq381.yaml").write_text(yaml.dump([
        {"title": "DQ381 mechatronic solenoid wear", "domain": "transmission"},
        {"title": "DQ200 hydraulic pressure failure", "domain": "transmission"},
    ]))
    (new / "dq381.yaml").write_text(yaml.dump([
        {"title": "Mechatronic solenoid wear on DQ381", "domain": "transmission"},
    ]))
    report = parity.compare([old], new)
    assert "matched: 1" in report
    assert "DQ200 hydraulic pressure failure" in report  # only-in-existing, listed
