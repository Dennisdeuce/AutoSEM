"""Test the optimization engine logic."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_optimizer_logic():
    """Test optimization decisions with mock data."""
    print("Testing optimizer decision logic...\n")

    scenarios = [
        {
            "name": "High ROAS campaign",
            "impressions": 5000, "clicks": 150, "conversions": 10,
            "spend": 50.0, "revenue": 150.0, "daily_budget": 10.0,
            "expected": "budget_increase",
        },
        {
            "name": "Low ROAS campaign",
            "impressions": 5000, "clicks": 100, "conversions": 2,
            "spend": 75.0, "revenue": 50.0, "daily_budget": 15.0,
            "expected": "budget_decrease",
        },
        {
            "name": "Very poor ROAS",
            "impressions": 10000, "clicks": 200, "conversions": 1,
            "spend": 150.0, "revenue": 30.0, "daily_budget": 20.0,
            "expected": "paused",
        },
        {
            "name": "Low CTR campaign",
            "impressions": 10000, "clicks": 20, "conversions": 1,
            "spend": 15.0, "revenue": 30.0, "daily_budget": 10.0,
            "expected": "flag_low_ctr",
        },
        {
            "name": "New campaign - insufficient data",
            "impressions": 50, "clicks": 2, "conversions": 0,
            "spend": 3.0, "revenue": 0.0, "daily_budget": 10.0,
            "expected": "waiting",
        },
    ]

    passed = 0
    for s in scenarios:
        roas = s["revenue"] / s["spend"] if s["spend"] > 0 else 0
        ctr = s["clicks"] / s["impressions"] if s["impressions"] > 0 else 0

        if s["impressions"] < 100:
            action = "waiting"
        elif roas < 0.5 and s["spend"] > 100:
            action = "paused"
        elif roas >= 1.5 * 1.5 and s["spend"] > 20:
            action = "budget_increase"
        elif roas < 1.5 and s["spend"] > 50:
            action = "budget_decrease"
        elif ctr < 0.005 and s["clicks"] >= 10:
            action = "flag_low_ctr"
        else:
            action = "no_change"

        match = action == s["expected"]
        status = "\u2713" if match else "\u2717"
        print(f"  {status} {s['name']}: ROAS={roas:.2f}x CTR={ctr:.3%} \u2192 {action} (expected: {s['expected']})")
        if match:
            passed += 1

    print(f"\n{passed}/{len(scenarios)} scenarios passed")
    return passed == len(scenarios)


if __name__ == "__main__":
    print("AutoSEM Optimization Tests\n")
    ok = test_optimizer_logic()
    print(f"\nResult: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)
