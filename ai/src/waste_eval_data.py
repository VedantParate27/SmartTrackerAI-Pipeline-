"""
Labeled test cases for evaluating the waste image classifier and pipeline.
Each entry names an image file (relative to the images/ folder) and the
expected classification result.
"""

WASTE_TEST_CASES = [
    {
        "image": "domestic_trial.jpg",
        "expected_usable": True,
        "expected_waste_type": "wet",
        "expected_severity": "domestic",
        "expected_escalate": False,
    },
    {
        "image": "garbage_dump_trial.jpg",
        "expected_usable": True,
        "expected_waste_type": "mixed",
        "expected_severity": "dump_scale",
        "expected_escalate": True,
    },
    {
        "image": "full_bin.jpeg",
        "expected_usable": True,
        "expected_waste_type": "mixed",
        "expected_severity": "moderate",
        "expected_escalate": False,
    },
    {
        "image": "dog.jpeg",
        "expected_usable": False,
        "expected_waste_type": "none",
        "expected_severity": "none",
        "expected_escalate": False,
    },
    {
        "image": "blurry.jpeg",
        "expected_usable": False,
        "expected_waste_type": "none",
        "expected_severity": "none",
        "expected_escalate": False,
    },
    {
        "image": "clean_street.jpg",
        "expected_usable": False,
        "expected_waste_type": "none",
        "expected_severity": "none",
        "expected_escalate": False,
    },
]