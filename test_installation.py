"""Test that all dependencies are installed correctly."""
import sys

def test_imports():
    modules = [("fastapi","FastAPI"),("uvicorn","Uvicorn"),("sqlalchemy","SQLAlchemy"),("pydantic","Pydantic"),("httpx","HTTPX"),("jinja2","Jinja2"),("dotenv","python-dotenv")]
    passed = 0
    failed = 0
    for module, name in modules:
        try:
            __import__(module)
            print(f"  OK {name}")
            passed += 1
        except ImportError:
            print(f"  FAIL {name}")
            failed += 1
    print(f"\n{passed}/{passed + failed} dependencies available")
    return failed == 0

def test_app_import():
    try:
        from main import app
        print("  OK FastAPI app loads")
        return True
    except Exception as e:
        print(f"  FAIL App: {e}")
        return False

if __name__ == "__main__":
    print("AutoSEM Installation Test\n")
    deps_ok = test_imports()
    app_ok = test_app_import()
    print(f"\nResult: {'PASS' if deps_ok and app_ok else 'FAIL'}")
    sys.exit(0 if deps_ok and app_ok else 1)
