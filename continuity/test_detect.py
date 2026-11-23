"""
continuity/test_detect.py
-------------------------
Verifies Pass 1 and Pass 2 contradiction detection.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from continuity.detect import pass_1_value_conflicts, pass_2_state_errors

def test_detect():
    print("=== Testing detect.py (Pass 1 & Pass 2) ===")

    # Mock Series Bible
    test_bible = {
        "Daniel Cole": {
            "eye_color": [
                {
                    "value": "blue",
                    "ep": 1,
                    "timestamp": "00:14",
                    "quote": "Daniel stared with cold blue eyes.",
                    "reliability": "stated"
                },
                {
                    "value": "brown",
                    "ep": 5,
                    "timestamp": "01:20",
                    "quote": "His brown eyes flashed in anger.",
                    "reliability": "stated"
                }
            ],
            "status": [
                {
                    "value": "arrested and jailed",
                    "ep": 3,
                    "timestamp": "02:10",
                    "quote": "Daniel Cole was arrested and locked in jail.",
                    "reliability": "stated"
                },
                {
                    "value": "speaking at boardroom",
                    "ep": 4,
                    "timestamp": "00:30",
                    "quote": "Daniel Cole addressed the board members.",
                    "reliability": "stated"
                }
            ]
        }
    }

    # Pass 1 Test
    v_conflicts = pass_1_value_conflicts(test_bible)
    print(f"Pass 1 detected {len(v_conflicts)} value conflicts.")
    assert len(v_conflicts) == 2, f"Expected 2 conflicts (eye_color & status), got {len(v_conflicts)}"
    assert v_conflicts[0]["fact_a"]["quote"]
    assert v_conflicts[0]["fact_b"]["quote"]

    # Pass 2 Test
    s_errors = pass_2_state_errors(test_bible)
    print(f"Pass 2 detected {len(s_errors)} state errors.")
    assert len(s_errors) == 1, f"Expected 1 state error, got {len(s_errors)}"
    err = s_errors[0]
    assert err["state_category"] == "arrested"
    print(f"[OK] State Error Caught: {err['description']}")

    print("\n[SUCCESS] detect.py verification passed flawlessly!")

if __name__ == "__main__":
    test_detect()
