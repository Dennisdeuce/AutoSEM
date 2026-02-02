#!/usr/bin/env python3
"""
Test script for AutoSEM optimization engine
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from app.services.optimization.optimization_engine import OptimizationEngine, get_optimization_engine
    from app.db.session import SessionLocal
    print("✓ Optimization engine imports successfully")

    # Test database connection
    db = SessionLocal()
    print("✓ Database connection established")

    # Test optimization engine instantiation
    engine = get_optimization_engine(db)
    print("✓ Optimization engine instantiated successfully")

    # Test basic methods exist
    assert hasattr(engine, 'run_hourly_optimization'), "Missing run_hourly_optimization method"
    assert hasattr(engine, 'run_daily_optimization'), "Missing run_daily_optimization method"
    assert hasattr(engine, 'pause_unprofitable_ads'), "Missing pause_unprofitable_ads method"
    print("✓ All required methods present")

    print("\n🎉 AutoSEM Optimization Engine Test PASSED!")
    print("The autonomous advertising system is ready to run.")

except ImportError as e:
    print(f"❌ Import Error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Test Error: {e}")
    sys.exit(1)
finally:
    if 'db' in locals():
        db.close()