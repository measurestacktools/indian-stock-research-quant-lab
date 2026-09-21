import subprocess, sys
print("Starting Stock Lab...")
subprocess.run([sys.executable, "-m", "streamlit", "run", "app/ui/main.py", "--server.port=8501"])
