#!/usr/bin/env python3
"""
Test script to validate AutoSEM installation
"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app.main import app
    print("✅ App imports successfully")
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

try:
    from app.core.config import settings
    print("✅ Settings loaded")
except Exception as e:
    print(f"❌ Settings error: {e}")
    sys.exit(1)

try:
    from app.db.session import engine
    print("✅ Database connection configured")
except Exception as e:
    print(f"❌ Database error: {e}")
    sys.exit(1)

try:
    from app.services.optimization import get_optimization_engine
    from app.db.session import SessionLocal
    db = SessionLocal()
    engine = get_optimization_engine(db)
    print("✅ Optimization engine initialized")
    db.close()
except Exception as e:
    print(f"❌ Optimization engine error: {e}")
    sys.exit(1)

print("\n🎉 AutoSEM is ready to run!")
print("Next steps:")
print("1. Set up your .env file with API credentials")
print("2. Run: python sync_data.py")
print("3. Start the scheduler: python scheduler.py")
print("4. Start the API server: uvicorn app.main:app --reload")