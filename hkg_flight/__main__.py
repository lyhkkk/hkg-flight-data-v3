"""
HKG Flight Data v3 - Module runner
Allows running the package with 'python -m hkg_flight'
"""

from .cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
