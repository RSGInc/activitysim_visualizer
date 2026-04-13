"""Tour time-of-day profiles.

Uses primary_purpose string directly from ActivitySim outputs.
Purposes are discovered from data, not hardcoded.
"""

import polars as pl
from .reader import RunData, Config
