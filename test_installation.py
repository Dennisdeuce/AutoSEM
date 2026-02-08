"""Test that all dependencies are installed correctly."""
import sys

def test_imports():
    modules = [
        ("fastapi", "FastAPI"), ("uvicorn", "Uvicorn"), ("sqlalchemy", "SQLAlchemy"),
        ("pydantic", "Pydantic"), ("httpx", "HTTPX"), ("jinja2", "Jinja2"), ("dotenv", "python-dotenv"),
    ]
    passed = failed = 0
    for module, name in modules:
        try:
            __import__(module)
            print(f"  \u2713 {name}")
            passed += 1
        except ImportError:
            print(f"  \u2717 {name} - NOT INSTALLED")
            failed += 1
    print(f"\n{passed}/{passed + failed} dependencies available")
    return failed == 0

def test_app_import():
    try:
        from main import app
        print("  \u2713 FastAPI app loads successfully")
        return True
    except Exception as e:
        print(f"  \u2717 App failed to load: {e}")
        return False

if __name__ == "__main__":
    print("AutoSEM Installation Test\n")
    print("Checking dependencies:")
    deps_ok = test_imports()
    print("\nChecking app:")
    app_ok = test_app_import()
    print(f"\nResult: {'PASS' if deps_ok and app_ok else 'FAIL'}")
    sys.exit(0 if deps_ok and app_ok else 1)
