"""`python -m gateway` is an alias for the preprocess CLI."""

import sys

from gateway.preprocess import main

sys.exit(main())
