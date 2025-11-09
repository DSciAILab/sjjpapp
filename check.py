import sys
import os
import subprocess
import importlib.util
import platform

print("="*60)
print("🔍 SUPABASE ENVIRONMENT CHECK")
print("="*60)

# 1️⃣ Python path and version
print(f"Python executable: {sys.executable}")
print(f"Python version: {platform.python_version()}")

# 2️⃣ Virtual environment detection
if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
    print("✅ Virtual environment detected.")
else:
    print("⚠️  Not running inside a virtual environment.")
    print("    Activate it with:")
    print("    source /Users/caravana/sjjp_app_novo/.venv/bin/activate")

# 3️⃣ Check installed packages
print("\n📦 Checking supabase installation...")
try:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "show", "supabase-py"],
        capture_output=True, text=True
    )
    if result.returncode == 0 and "Name: supabase-py" in result.stdout:
        print("✅ Package 'supabase-py' is installed.")
        lines = [line for line in result.stdout.splitlines() if line.startswith(("Name", "Version", "Location"))]
        for l in lines:
            print("   ", l)
    else:
        print("❌ Package 'supabase-py' not found. Try installing with:")
        print("   pip install supabase-py")
except Exception as e:
    print("⚠️  Could not check supabase-py:", e)

# 4️⃣ Try to import
print("\n🧠 Import test:")
try:
    from supabase import create_client
    print("✅ Import success: 'create_client' is available.")
except Exception as e:
    print("❌ Import failed:", e)

# 5️⃣ Show pip list summary
print("\n📋 Installed supabase-related packages:")
subprocess.run([sys.executable, "-m", "pip", "list"], text=True)

print("\n✅ Check complete.")
print("="*60)