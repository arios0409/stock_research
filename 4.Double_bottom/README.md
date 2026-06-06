# Stock Research

Tools for researching stock market patterns using Python.

## Scripts

### Double Bottom Scanner (`double_bottom_scanner.py`)
Scans for Double Bottom (W-bottom) breakouts in A-shares (Shanghai/Shenzhen 300 + CSI 500).

**Features:**
- Detects valid Double Bottom patterns.
- Filters for recent breakouts (within 10 days).
- Calculates risk/reward ratio (target vs current price).
- Generates SVG/PNG charts.

**Usage:**
1. Set your Tushare token in the script (`TUSHARE_TOKEN`).
2. Run: `python3 double_bottom_scanner.py`

**Dependencies:**
- Python 3 (Standard library only, no pip install needed!)
- `magick` (ImageMagick) for PNG conversion (optional).

## Setup

### 1. Install dependencies (Termux)
```bash
pkg install -y imagemagick
```

### 2. Run
```bash
python3 double_bottom_scanner.py
```
