"""Double-click to start Renkit without a console window."""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
os.chdir(here)
sys.path.insert(0, here)
from renkit import main  # noqa: E402

main()
