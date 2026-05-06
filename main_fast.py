"""
Pharma Compliance Pipeline – FAST MODE for Demo

Usage: python main_fast.py <path_to_pdf>

This version skips:
- Plot generation (optional per assignment)
- RAG verification (faster validation)

Use this for quick demos to reviewers.
"""

import os
os.environ["ENABLE_PLOTS"] = "false"
os.environ["ENABLE_RAG_VERIFICATION"] = "false"

# Now import and run the normal main
from main import main

if __name__ == "__main__":
    print("🚀 FAST MODE - Skipping plots and RAG verification for speed")
    print("=" * 80)
    main()
