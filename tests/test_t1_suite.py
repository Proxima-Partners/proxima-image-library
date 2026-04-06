import json

from scripts.run_t1_suite import run_t1_suite


def test_t1_automated_regression_suite():
    report = run_t1_suite()
    assert report.get("overall_ok"), json.dumps(report, indent=2)
