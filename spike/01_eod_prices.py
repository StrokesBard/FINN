"""Spike 1: end-of-day price & volume.

Candidates:
  a) Yahoo Finance chart API (what yfinance calls)  -> robots check only
  b) NSE CM bhavcopy, new UDiFF format (Jul 2024+)  -> nsearchives.nseindia.com
  c) NSE "sec_bhavdata_full" (adds delivery qty)
  d) NSE legacy bhavcopy (pre Jul 2024)             -> history depth
  e) BSE bhavcopy (UDiFF)
"""
import io
import sys
import zipfile
from datetime import date, timedelta

import pandas as pd

from _common import get, robots_verdict

TODAY = date.today()
SAMPLE = ["RELIANCE", "HDFCBANK", "INFY", "TATAMOTORS", "IRCTC"]


def weekdays_back(n):
    d, out = TODAY, []
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


print(f"Today: {TODAY}\n")

print("a) Yahoo chart API (yfinance backend)")
for u in ["https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS",
          "https://query2.finance.yahoo.com/v8/finance/chart/RELIANCE.NS"]:
    ok, note = robots_verdict(u)
    print(f"  robots allowed={ok} ({note}) {u}")

print("\nb) NSE UDiFF bhavcopy, last 8 weekdays")
latest = None
for d in weekdays_back(8):
    u = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    r = get(u)
    if r is not None and r.status_code == 200 and r.content[:2] == b"PK":
        if latest is None:
            latest = (d, r.content)
if latest:
    d, blob = latest
    zf = zipfile.ZipFile(io.BytesIO(blob))
    df = pd.read_csv(zf.open(zf.namelist()[0]))
    print(f"\n  latest file {d}: {len(df):,} rows, columns:\n  {list(df.columns)}")
    print(f"  series counts: {df['SctySrs'].value_counts().head(8).to_dict()}")
    eq = df[(df["SctySrs"] == "EQ") & (df["TckrSymb"].isin(SAMPLE))]
    print(eq[["TckrSymb", "ISIN", "FinInstrmNm", "OpnPric", "HghPric", "LwPric",
              "ClsPric", "PrvsClsgPric", "TtlTradgVol", "TradDt"]].to_string(index=False))
    missing = set(SAMPLE) - set(eq["TckrSymb"])
    if missing:
        print(f"  NOT FOUND as EQ series: {missing}")

print("\nc) NSE sec_bhavdata_full (delivery data)")
for d in weekdays_back(4):
    u = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv"
    r = get(u)
    if r is not None and r.status_code == 200 and b"SYMBOL" in r.content[:200]:
        df = pd.read_csv(io.BytesIO(r.content))
        df.columns = [c.strip() for c in df.columns]
        print(f"  {d}: {len(df):,} rows, columns: {list(df.columns)}")
        break

print("\nd) History depth")
probes = {
    "UDiFF 2024-07-08": "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20240708_F_0000.csv.zip",
    "UDiFF 2023-01-02": "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20230102_F_0000.csv.zip",
    "legacy 2024-07-05": "https://nsearchives.nseindia.com/content/historical/EQUITIES/2024/JUL/cm05JUL2024bhav.csv.zip",
    "legacy 2020-01-02": "https://nsearchives.nseindia.com/content/historical/EQUITIES/2020/JAN/cm02JAN2020bhav.csv.zip",
    "legacy 2026-10-30": "https://nsearchives.nseindia.com/content/historical/EQUITIES/2026/OCT/cm30OCT2026bhav.csv.zip",
}
for label, u in probes.items():
    r = get(u)
    ok = r is not None and r.status_code == 200 and r.content[:2] == b"PK"
    print(f"    -> {label}: {'zip OK' if ok else 'not available'}")

print("\ne) BSE UDiFF bhavcopy")
for d in weekdays_back(4):
    u = f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{d:%Y%m%d}_F_0000.CSV"
    r = get(u)
    if r is not None and r.status_code == 200 and b"TradDt" in r.content[:300]:
        df = pd.read_csv(io.BytesIO(r.content))
        print(f"  {d}: {len(df):,} rows; sample:")
        print(df[df["TckrSymb"].isin(SAMPLE)][["TckrSymb", "FinInstrmId", "ISIN", "ClsPric",
                                                "TtlTradgVol"]].to_string(index=False))
        break
    elif r is not None:
        print(f"    body head: {r.content[:120]!r}")

sys.exit(0)
