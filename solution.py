"""
Avathon Data Analysis Case Study
Dataset : Device*.csv  (long format, ~7.5M rows per device)

What this script does, in order:
  STEP 1  : Load the raw data
  STEP 2  : Understand & measure data quality          (Task A)
  STEP 3  : Identify non-aggregatable signals          (Task B)
  STEP 4  : Handle NaN values + scatter plot           (Task C)
  STEP 5  : Pivot long → wide format
  STEP 6  : Build 10-min aggregate table               (Task 1)
  STEP 7  : Add LA timezone column                     (Task D)
  STEP 8  : General function for any time resolution   (Task E)
  STEP 9  : Visualizations — time-series + scatter     (Task 2)


Device*.csv files is in the same folder as this script.
Outputs go into the  ./output/  folder.
"""

import os
import glob
import polars as pl
import matplotlib
matplotlib.use("Agg")          # save to file, no pop-up window needed
import matplotlib.pyplot as plt

# Folder setup 
OUTPUT_DIR = "./output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

#  STEP 1 — Load the raw data

print("\n" + "="*55)
print("  STEP 1 — Load raw data")
print("="*55)

# Find all Device CSV files in current folder
csv_files = sorted(glob.glob("Device*.csv"))

if not csv_files:
    print("ERROR: No Device*.csv files found in current folder.")
    print("Place your CSV files here and run again.")
    exit()

print(f"Found {len(csv_files)} file(s): {csv_files}")

# Load and stack all device files into one DataFrame
frames = []
for f in csv_files:
    print(f"  Loading {f} ...")
    df_one = pl.read_csv(
        f,
        schema={
            "TimeStamp" : pl.String,
            "variable"  : pl.String,
            "value"     : pl.Float64,
            "device"    : pl.String,
        }
    ).with_columns(
        pl.col("TimeStamp").str.to_datetime(
            format="%Y-%m-%d %H:%M:%S%.f",
            strict=False
        )
    )
    frames.append(df_one)

df = pl.concat(frames)

print(f"\nTotal rows loaded : {df.shape[0]:,}")
print(f"Columns           : {df.columns}")
print(f"Devices           : {df['device'].unique().to_list()}")
print(f"Signals (30 total): {sorted(df['variable'].unique().to_list())}")
print(f"Time range        : {df['TimeStamp'].min()}  →  {df['TimeStamp'].max()}")
print(f"\nFirst 5 rows:")
print(df.head(5))



#  STEP 2 — Understand & measure data quality  (Task A)

print("\n" + "="*55)
print("  STEP 2 — Data Quality Assessment  (Task A)")
print("="*55)

#
#  Issues to watch for:
#   1. Missing (NaN) values   — sensor dropout or comms failure
#   2. Duplicate timestamps   — device re-sent buffered data
#   3. Large sampling gaps    — device was offline
#   4. Stuck sensors          — value never changes (std = 0)
#

# --- Issue 1: NaN rate per signal ---
print("\n--- NaN rate per signal ---")
nan_report = (
    df.group_by("variable")
    .agg([
        pl.col("value").count().alias("readings"),
        pl.col("value").is_null().sum().alias("missing"),
    ])
    .with_columns(
        (pl.col("missing") /
         (pl.col("readings") + pl.col("missing")) * 100)
        .round(1).alias("missing_%")
    )
    .sort("missing_%", descending=True)
)
print(nan_report)
nan_report.write_csv(os.path.join(OUTPUT_DIR, "data_quality_report.csv"))
print("-> Saved: output/data_quality_report.csv")

# --- Issue 2: Duplicate timestamps ---
print("\n--- Duplicate (TimeStamp + variable) rows ---")
total     = df.shape[0]
uniq      = df.unique(subset=["TimeStamp","variable","device"]).shape[0]
dup_count = total - uniq
print(f"Duplicates found: {dup_count:,}")

# --- Issue 3: Sampling gap ---
print("\n--- Sampling interval ---")
gaps = (
    df.select("TimeStamp").unique().sort("TimeStamp")
    .with_columns(
        pl.col("TimeStamp").diff()
        .dt.total_seconds().alias("gap_sec")
    ).drop_nulls()
)
print(f"  Median gap : {gaps['gap_sec'].median():.1f} seconds")
print(f"  Max gap    : {gaps['gap_sec'].max():.0f} seconds")

####################################################

print("\n--- Sampling interval (per device) ---")

for device in sorted(df["device"].unique().to_list()):

    gaps = (
        df.filter(pl.col("device") == device)   # ← only THIS device
        .select("TimeStamp")
        .unique()
        .sort("TimeStamp")
        .with_columns(
            pl.col("TimeStamp").diff()
            .dt.total_seconds()
            .alias("gap_sec")
        )
        .drop_nulls()
    )

    print(f"  {device}:  "
          f"median = {gaps['gap_sec'].median():.1f}s  "
          f"max gap = {gaps['gap_sec'].max():.0f}s")



# --- Issue 4: Stuck sensors ---
print("\n--- Stuck sensors (std = 0 across all readings) ---")
stuck = (
    df.group_by("variable")
    .agg(pl.col("value").std().alias("std"))
    .filter(pl.col("std") == 0)
)
if stuck.shape[0] == 0:
    print("  None found.")
else:
    print(stuck)



#  STEP 3 — Identify non-aggregatable signals  (Task B)

print("\n" + "="*55)
print("  STEP 3 — Non-aggregatable signals  (Task B)")
print("="*55)


#
#  TEST 1 — Label / status code
#    Question : Does this signal have very few unique whole-number values?
#    Check    : n_unique <= 15  AND  all values are integers
#    Why      : Real sensors produce hundreds of unique values.
#               A column with only 5 unique whole numbers is storing
#               category labels (like 1=start, 3=run, 6=fault),
#               not continuous measurements.
#               Averaging labels is meaningless.
#
#  TEST 2 — Circular / directional signal (compass)
#    Question : Does this signal have values near BOTH 0 and 360?
#    Check    : range > 300  AND  min < 10  AND  max > 350  AND  max <= 400
#    Why      : Compass bearings wrap around at 360°.
#               Mean of 1° and 359° = 180° (south) — completely wrong.
#               The real average direction is 0° (north).
#               We add max <= 400 to avoid flagging electrical signals
#               like Amps or Watts that also start near 0 but go into
#               the thousands — those are NOT compass directions.
#

NON_AGG  = []  
safe_sigs = [] 

all_signals = sorted(df["variable"].unique().to_list())

print(f"\nRunning 2 tests on all {len(all_signals)} signals...\n")
print(f"  {'Signal':<30}  {'Test result':<15}  Reason")
print("  " + "-" * 75)

for signal_name in all_signals:

    # Pull out this signal's values, sorted by time, NaN removed
    vals = (
        df.filter(pl.col("variable") == signal_name)
        .sort("TimeStamp")["value"]
        .drop_nulls()
    )

    n = vals.shape[0]

    # Not enough readings to decide — skip
    if n < 10:
        print(f"  {signal_name:<30}  {'SKIP':<15}  "
              f"only {n} non-null readings")
        continue

    # ── Calculate the 5 numbers used by the 2 tests ──────
    n_unique   = vals.n_unique()
    pct_int    = (vals % 1 == 0).mean() * 100      # % whole numbers
    val_min    = vals.min()
    val_max    = vals.max()
    val_range  = val_max - val_min

    #  TEST 1: Label / status code 
    if n_unique <= 15 and pct_int == 100.0:
        NON_AGG.append(signal_name)
        print(f"  {signal_name:<30}  {'DO NOT AVERAGE':<15}  "
              f"Test 1: {n_unique} unique whole-number values "
              f"{sorted(vals.unique().to_list())} -> label/status code")



    #  TEST 2: Circular / directional 
    elif (val_range > 300
          and val_min  < 10
          and val_max  > 350
          and val_max  <= 400):
        NON_AGG.append(signal_name)
        print(f"  {signal_name:<30}  {'DO NOT AVERAGE':<15}  "
              f"Test 2: min={val_min:.0f}, max={val_max:.0f}, "
              f"range={val_range:.0f} -> circular direction")

    #  All 2 tests passed → safe to average 
    else:
        safe_sigs.append(signal_name)
        print(f"  {signal_name:<30}  {'SAFE TO AVERAGE':<15}  "
              f"{n_unique} unique values, range={val_range:.1f}")

print(f"\nResult -> DO NOT AVERAGE : {NON_AGG}")
print(f"Result -> SAFE TO AVERAGE: {sorted(safe_sigs)}")



#  STEP 4 — Handle NaN values + scatter plot  (Task C)

print("\n" + "="*55)
print("  STEP 4 — Handle NaN values  (Task C)")
print("="*55)

#
#  Strategy:
#    Short gaps (≤3 missing readings = ~4.5 sec):
#      → Forward fill  (copy last known value forward)
#    Medium gaps (≤5 more readings = ~7.5 sec):
#      → Linear interpolation (draw a line between known points)
#    Long gaps (anything remaining):
#      → Leave as NaN  (device was offline, we don't want to invent data)
#
#  Why not fill everything?
#    If a sensor is offline for 30 minutes, guessing values
#    would corrupt analytics.
#

nan_before = df["value"].is_null().sum()
print(f"NaN rows before: {nan_before:,}  "
      f"({100*nan_before/df.shape[0]:.1f}%)")

# ════════════════════════════════════════════════════════════
#  TASK C — NaN scatter plot: before and after, per device
#
#  Simple 4-step approach:
#    Step 1 : pick a signal to plot
#    Step 2 : get BEFORE data  (raw, with NaN)
#    Step 3 : get AFTER data   (NaN filled)
#    Step 4 : draw two charts side by side
# ════════════════════════════════════════════════════════════

# ── Step 1: Pick a signal to plot ───────────────────────────
# We use MMXN1_Amp — it has clear NaN gaps, easy to visualise
plot_signal = "MMXN1_Amp"
print(f"Plotting NaN scatter for signal: {plot_signal}")

#  Fill NaN first (needed for AFTER data) 
print("Filling short NaN gaps...")
filled_parts = []
for var in df["variable"].unique().to_list():
    part = (
        df.filter(pl.col("variable") == var)
        .sort("TimeStamp")
        .with_columns(
            pl.col("value")
            .forward_fill(limit=3)  # copy last value forward (max 3 gaps)
            .interpolate()          # fill remaining with straight line
            .alias("value")
        )
    )
    filled_parts.append(part)

df_clean = pl.concat(filled_parts).sort("TimeStamp")

nan_after = df_clean["value"].is_null().sum()
print(f"NaN rows after : {nan_after:,}  "
      f"({100*nan_after/df_clean.shape[0]:.1f}%)")
print(f"Rows filled in : {nan_before - nan_after:,}")

#  One plot per device 
all_devices = sorted(df["device"].unique().to_list())

for device in all_devices:

    # Step 2: BEFORE data — raw values for this signal + device
    before = (
        df.filter(
            (pl.col("variable") == plot_signal) &
            (pl.col("device")   == device)
        )
        .sort("TimeStamp")
        .to_pandas()
    )

    # Step 3: AFTER data — filled values for this signal + device
    after = (
        df_clean.filter(
            (pl.col("variable") == plot_signal) &
            (pl.col("device")   == device)
        )
        .sort("TimeStamp")
        .to_pandas()
    )

    if before.empty:
        continue

    # Step 4: Draw two charts side by side
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle(
        f"Task C — NaN Handling | {plot_signal} | {device}",
        fontsize=13, fontweight="bold"
    )

    # LEFT chart — BEFORE (raw data with gaps)
    ax1.scatter(
        before["TimeStamp"],  # x axis = time
        before["value"],      # y axis = sensor value (NaN rows just don't appear)
        s=2,
        color="blue",
        alpha=0.5
    )
    nan_count = before["value"].isna().sum()
    total     = len(before)
    ax1.set_title(f"BEFORE  —  {nan_count:,} NaN out of {total:,} rows "
                  f"({100*nan_count/total:.0f}% missing)")
    ax1.set_xlabel("Time")
    ax1.set_ylabel("Value")
    ax1.tick_params(axis="x", rotation=30)

    # RIGHT chart — AFTER (gaps filled)
    ax2.scatter(
        after["TimeStamp"],   # x axis = time
        after["value"],       # y axis = sensor value (gaps now filled)
        s=2,
        color="green",
        alpha=0.5
    )
    nan_remaining = after["value"].isna().sum()
    ax2.set_title(f"AFTER  —  {nan_remaining:,} NaN remaining "
                  f"(long outages kept empty)")
    ax2.set_xlabel("Time")
    ax2.set_ylabel("Value")
    ax2.tick_params(axis="x", rotation=30)

    plt.tight_layout()
    out_path = os.path.join(OUTPUT_DIR,
                            f"task_c_nan_scatter_{device}.png")
    plt.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close()
    print(f"-> Saved: {out_path}")



#  STEP 5 — Pivot: long format → wide format

print("\n" + "="*55)
print("  STEP 5 — Pivot long → wide format")
print("="*55)

#
#  The raw data is "long" format:
#    One row = one sensor reading
#    Many rows share the same timestamp (different signals)
#
#  We need "wide" format:
#    One row = one timestamp
#    Each signal becomes its own column
#
#  This is required before we can do time-based aggregation.
#

# Remove duplicate (TimeStamp, variable, device) rows first
df_clean = df_clean.unique(subset=["TimeStamp","variable","device"])

wide = (
    df_clean
    .pivot(
        index= ["TimeStamp","device"],
        on= "variable",
        values= "value",
        aggregate_function= "mean",
    )
    .sort("TimeStamp")
)

sig_cols = [c for c in wide.columns if c not in ("TimeStamp","device")]
print(f"Wide format shape : {wide.shape}  "
      f"({wide.shape[0]:,} rows × {wide.shape[1]} columns)")
print(f"Signal columns    : {len(sig_cols)}")
print(f"\nSample (4 columns shown):")
print(wide.select(["TimeStamp","device"] + sig_cols[:4]).head(4))



#  STEP 6 — 10-min aggregation  (Task 1)

print("\n" + "="*55)
print("  STEP 6 — 10-min Aggregation  (Task 1)")
print("="*55)

#
#  For every 10-minute window, compute:
#    _Avg    = average value in that window
#    _Min    = minimum value
#    _Max    = maximum value
#    _Last   = last value recorded in the window
#    _StdDev = how much the values varied (standard deviation)
#
#  Non-aggregatable signals get _Last only.
#

agg_cols    = [c for c in sig_cols if c not in NON_AGG]
nonagg_cols = [c for c in sig_cols if c in NON_AGG]

# Build the list of expressions
exprs = []
for col in agg_cols:
    exprs += [
        pl.col(col).mean() .alias(f"{col}_Avg"),
        pl.col(col).min()  .alias(f"{col}_Min"),
        pl.col(col).max()  .alias(f"{col}_Max"),
        pl.col(col).last() .alias(f"{col}_Last"),
        pl.col(col).std()  .alias(f"{col}_StdDev"),
    ]
for col in nonagg_cols:
    exprs.append(pl.col(col).last().alias(f"{col}_Last"))

# Aggregate
agg_10min = (
    wide
    .sort("TimeStamp")
    .group_by_dynamic("TimeStamp", every="10m", group_by="device")
    .agg(exprs)
    .sort(["device","TimeStamp"])
    .rename({"TimeStamp": "timestamp"})
)

print(f"10-min aggregate shape : {agg_10min.shape}")
print(f"  = {agg_10min.shape[0]:,} rows  ×  {agg_10min.shape[1]} columns")
print(f"\nSample output (power signal):")
power_cols = ["timestamp","device"] + \
             [c for c in agg_10min.columns if "WTUR1_W" in c]
print(agg_10min.select(power_cols).head(3))

# Save
agg_10min.write_csv(os.path.join(OUTPUT_DIR, "aggregated_10min.csv"))
print("\n-> Saved: output/aggregated_10min.csv ")



#  STEP 7 — Add LA timezone column  (Task D)

print("\n" + "="*55)
print("  STEP 7 — Add timestamp_z column  (Task D)")
print("="*55)

#
#  The devices log timestamps in UTC.

agg_10min = agg_10min.with_columns(
    pl.col("timestamp")
    .dt.replace_time_zone("UTC")
    .dt.convert_time_zone("America/Los_Angeles")
    .alias("timestamp_z")
)

# Move timestamp_z to be the second column
cols = agg_10min.columns
cols.remove("timestamp_z")
cols.insert(1, "timestamp_z")
agg_10min = agg_10min.select(cols)

print("timestamp_z column added.")
print(agg_10min.select(["timestamp","timestamp_z"]).head(4))
print("\nNote: UTC 00:00 → LA 17:00 the previous day (PDT = UTC-7)")

# Save updated version
agg_10min.write_csv(os.path.join(OUTPUT_DIR, "aggregated_10min_with_tz.csv"))
print("-> Saved: output/aggregated_10min_with_tz.csv")



#  STEP 8 — General aggregation function  (Task E)

print("\n" + "="*55)
print("  STEP 8 — General aggregation function  (Task E)")
print("="*55)

#
#  One function that works for ANY time resolution.
#  Just change the 'freq' parameter:
#    "1m"   1-minute bins
#    "5m"   5-minute bins
#    "10m"  10-minute bins
#    "1h"   hourly bins
#

def aggregate(wide_df, freq, non_agg_signals):
    """
    Aggregate wide-format sensor data to any time resolution.

    Parameters
    ----------
    wide_df          : Polars DataFrame (wide format, TimeStamp as column)
    freq             : time bin size — "1m", "5m", "10m", "1h", "1d" etc.
    non_agg_signals  : list of signal names to NOT average (get Last only)

    Returns
    -------
    Polars DataFrame with one row per time bin and per device
    """
    sig_cols    = [c for c in wide_df.columns
                   if c not in ("TimeStamp","device")]
    agg_cols    = [c for c in sig_cols if c not in non_agg_signals]
    nonagg_cols = [c for c in sig_cols if c in non_agg_signals]

    exprs = []
    for col in agg_cols:
        exprs += [
            pl.col(col).mean() .alias(f"{col}_Avg"),
            pl.col(col).min()  .alias(f"{col}_Min"),
            pl.col(col).max()  .alias(f"{col}_Max"),
            pl.col(col).last() .alias(f"{col}_Last"),
            pl.col(col).std()  .alias(f"{col}_StdDev"),
        ]
    for col in nonagg_cols:
        exprs.append(pl.col(col).last().alias(f"{col}_Last"))

    return (
        wide_df.sort("TimeStamp")
        .group_by_dynamic("TimeStamp", every=freq, group_by="device")
        .agg(exprs)
        .sort(["device","TimeStamp"])
        .rename({"TimeStamp": "timestamp"})
    )

# Produce 1-min, 5-min, and 1-hour aggregates
for label, freq in [("1min","1m"), ("5min","5m"), ("1h","1h")]:
    result = aggregate(wide, freq, NON_AGG)
    out    = os.path.join(OUTPUT_DIR, f"aggregated_{label}.csv")
    result.write_csv(out)
    print(f"  {label} → {result.shape[0]:,} rows -> {out}")


#  STEP 9 — Visualizations  (Task 2)

print("\n" + "="*55)
print("  STEP 9 — Visualizations  (Task 2)")
print("="*55)

# Convert to pandas for matplotlib for easier plotting
agg_pd = agg_10min.to_pandas()
agg_pd["timestamp"] = agg_pd["timestamp"].dt.tz_localize(None)

devices = sorted(agg_pd["device"].unique())
colors  = ["#2980b9","#e74c3c","#27ae60","#f39c12","#8e44ad","#16a085"]

# Chart 1: Time-series 
print("\nChart 1: Time-series...")

ts_signals = [
    ("WNAC1_WdSpd_Avg", "WNAC1_WdSpd_Avg"),
    ("WTUR1_W_Avg",     "WTUR1_W_Avg"),
    ("MMXN1_Amp_Avg",   "MMXN1_Amp_Avg"),
]
ts_signals = [(c, l) for c, l in ts_signals if c in agg_pd.columns]

fig, axes = plt.subplots(len(ts_signals), 1,
                         figsize=(14, 4*len(ts_signals)),
                         sharex=True)
if len(ts_signals) == 1:
    axes = [axes]

fig.suptitle("Task 2 — 10-min Aggregates: Time Series",
             fontsize=13, fontweight="bold")

for ax, (col, label) in zip(axes, ts_signals):
    for i, dev in enumerate(devices):
        sub = agg_pd[agg_pd["device"] == dev].sort_values("timestamp")
        ax.plot(sub["timestamp"], sub[col],
                label=dev, color=colors[i % len(colors)],
                linewidth=1.0, alpha=0.85)
    ax.set_ylabel(label, fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

axes[-1].set_xlabel("Timestamp (UTC)")
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, "task2_timeseries.png"),
            dpi=120, bbox_inches="tight")
plt.close()
print("-> Saved: output/task2_timeseries.png")

#  Chart 2: Scatter 
print("Chart 2")

x_col = "WNAC1_WdSpd_Avg"
y_col = "WTUR1_W_Avg"

if x_col in agg_pd.columns and y_col in agg_pd.columns:

    # One subplot per device 
    n_dev = len(devices)
    fig, axes = plt.subplots(1, n_dev, figsize=(6*n_dev, 5),
                                sharey=True)
    if n_dev == 1:
        axes = [axes]

    fig.suptitle(
        f"Task 2 —  Curve: {x_col}  vs  {y_col}\n"
        "(10-min averages, per device)",
        fontsize=12, fontweight="bold"
    )

    for ax, dev, color in zip(axes, devices, colors):
        sub = agg_pd[agg_pd["device"] == dev].dropna(
            subset=[x_col, y_col]
        )
        ax.scatter(sub[x_col], sub[y_col],
                   s=8, color=color, alpha=0.5)
        ax.set_title(dev, fontsize=11, fontweight="bold")
        ax.set_xlabel("WNAC1_WdSpd_Avg")
        ax.set_ylabel("WTUR1_W_Avg")
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "task2_scatter_power_curve.png"),
                dpi=120, bbox_inches="tight")
    plt.close()
    print("-> Saved: output/task2_scatter_power_curve.png")
else:
    print(f"  Skipped (signals {x_col} or {y_col} not in data)")



#  DONE

print("\n" + "="*55)
print("  ALL DONE")
print("="*55)
print(f"\nOutputs are in:  {os.path.abspath(OUTPUT_DIR)}/")
print("""
  data_quality_report.csv         Task A — NaN rates per signal
  task_c_nan_scatter_Device1.png          Task C — before/after NaN scatter for Device1 so on for each device
  aggregated_10min.csv            Task 1 — main deliverable
  aggregated_10min_with_tz.csv    Task D — with LA timezone column
  aggregated_1min.csv             Task E — 1-min resolution
  aggregated_5min.csv             Task E — 5-min resolution
  aggregated_1h.csv               Task E — hourly resolution
  task2_timeseries.png            Task 2 — time series chart
  task2_scatter_power_curve.png   Task 2 — wind vs power scatter
""")