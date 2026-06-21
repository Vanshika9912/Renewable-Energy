# Avathon Data Analysis — Observations Report

**Author:** Vanshika  
**Dataset:** 6  Devices  
**Tools used:** Python, Polars, Matplotlib  

---

## 1. Dataset Overview

We were given 6 CSV files, one per turbine device. After loading all 6 files together:

| Item | Value |
|------|-------|
| Total rows loaded | 46,648,470 |
| Total devices | 6 (Device1 to Device6) |
| Total signals per device | 30 |
| Time range | 2020-07-01 00:00:01 → 2020-07-07 23:49:58 |
| Data format | Long format — one row per sensor reading |

---

## 2. Observation 1 — Data Quality is Poor (88% Missing)

This was the most alarming finding. Before any cleaning:

- **41,145,967 out of 46,648,470 rows (88.2%) had no value at all**

That means nearly 9 out of every 10 rows were empty. This is much higher than what you would expect from healthy IoT devices. The team should investigate whether this is a known characteristic of how these edge devices log data, or whether there is a systemic issue with data collection infrastructure.

### NaN rate breakdown by signal

**Completely silent — 100% NaN (zero readings)**

Five signals reported absolutely nothing across all 7 days and all 6 devices: `WTUR1_TotWh`, `WTUR1_TotVArh`, `WTRF1_TrfTmpCell`, `WTRF1_TrfTmpWdg`, and `WROT1_RotSpd`. These sensors either are not installed, not connected, or have a hardware/software fault. This needs to be investigated by the field team.

**Nearly silent — ~100% NaN (handful of readings)**

- `WTUR1_TurSt_actSt` had only 672 real readings out of 1,554,949 possible rows.
- `WROT1_HubTmp` had only 767 readings out of 1,554,949 is a concern and should be flagged for hardware inspection.

**Moderate NaN — approximately 50% missing**

The majority of signals — including `MMXN1_Amp`, `WTUR1_W` , `WTUR1_VA` , and `WNAC1_WdDir`  — had roughly half their readings missing. This is the most common pattern across the dataset. Half of all readings being empty for core operational signals like power output is higher than expected and suggests the devices may be configured to log only on value change rather than at a fixed interval.

### What we did about it
We applied a two-step fill strategy:
- Forward fill for gaps of 1–3 consecutive NaN rows (~1.5 to 4.5 seconds) — safe to copy last known value
- Linear interpolation for any remaining NaN — draws a smooth line between surrounding real values
- Long outages left as NaN — we do not invent data across large gaps

**Result:** NaN reduced from 88.2% to 17.1%. We filled 33,161,130 rows. The remaining 17.1% are genuine long outages.

---

## 3. Observation 2 — All Devices Have the Same Sampling Pattern

Each device sends readings approximately every 1 second (median gap = 1.0 second across all 6 devices).

| Device | Median gap | Max gap (longest outage) |
|--------|-----------|--------------------------|
| Device1 | 1.0s | 74 seconds |
| Device2 | 1.0s | 69 seconds |
| Device3 | 1.0s | 70 seconds |
| Device4 | 1.0s | 61 seconds |
| Device5 | 1.0s | 53 seconds |
| Device6 | 1.0s | 79 seconds |

**Key observation:** All 6 devices had brief outages ranging from 53 to 79 seconds at some point during the 7 days. Device6 had the longest single outage (79 seconds) and Device5 had the shortest (53 seconds).

These outages are short enough that our fill strategy handles them reasonably well — we fill up to ~7.5 seconds and leave the rest as NaN. Any reading gaps beyond that in the 10-minute aggregate window are simply excluded from the average calculation.


---

## 4. Observation 3 — Three Signals Should NOT Be Averaged

After running automated tests on all 30 signals, 2 were flagged as non-aggregatable:

### WTUR1_TurSt_actSt — Turbine Status Code
Only 5 unique whole-number values: {1, 2, 3, 4, 6}.  
These are operating mode labels (1=initialising, 3=running, 6=fault). Averaging them gives meaningless results — the mean of fault(6) and running(3) = 4.5, which corresponds to no real state.  
**Decision:** Keep Last value only per 10-minute window.

### WNAC1_WdDir —  Direction 
Range = 0 to 359 — spans like the full compass circle.  
Averaging compass bearings with standard mean is geometrically wrong. Mean of 1° and 359° = 180° (south), when the true average direction is 0° (north).  
**Decision:** Keep Last value only.

### WNAC1_Dir —  Direction
Range = 1 to 359 — also spans the full compass circle.  
Same problem as wind direction — circular signal, standard mean does not apply.  
**Decision:** Keep Last value only.

### 5 signals were skipped entirely (all NaN)
WROT1_RotSpd, WTRF1_TrfTmpCell, WTRF1_TrfTmpWdg, WTUR1_TotVArh, WTUR1_TotWh — zero real readings across the entire dataset. These were excluded from aggregation.

### Remaining 22 signals — Safe to average
All other signals passed the automated tests and were aggregated normally with Avg, Min, Max, Last, and StdDev.

---

## 5. Observation 4 — The 10-Minute Aggregate Output

### Output shape
- **6,042 rows** × **140 columns**
- 6 devices × ~1,007 bins per device = 6,042 rows
- 22 safe signals × 5 stats = 110 columns + 3 non-agg Last columns + timestamp + device + timestamp_z = 140 columns

### Sample power output values (Device1, first 3 bins)

| Timestamp | Avg  | Min  | Max | Last   | StdDev |
|-----------|---------|---------|---------|----------|--------|
| 00:00:00 | 1,156 | 428 | 1,927 | 1,719 | 355 |
| 00:10:00 | 1,354 | 634 | 2,084 | 1,392 | 303 |
| 00:20:00 | 1,103 | 543 | 1,767 | 1,013 | 237 |

**What this tells us:** Power output in the first 30 minutes of July 1 ranged between 428W and 2,084W. The standard deviation of ~300W suggests moderate variability — the wind was fluctuating but the turbine was running. The minimum of 428W at 00:00 suggests the turbine was ramping up at the very start.

---

## 6. Observation 5 — Timezone Conversion

Source timestamps are in UTC. The customer operates in California (America/Los_Angeles).

- July 2020 → PDT (Pacific Daylight Time) = UTC − 7 hours
- Example: `2020-07-01 00:00:00 UTC` = `2020-06-30 17:00:00 PDT`

A `timestamp_z` column was added to the 10-minute aggregate table showing the equivalent LA time. This was built into Polars natively — no extra library required.

---

## 7. Observation 6 — Multi-Resolution Aggregates

Using a single reusable function, we produced 4 different time resolutions from the same cleaned dataset:

| Resolution | Rows | Use case |
|-----------|------|----------|
| 1-minute | 60,419 | Detailed fault analysis |
| 5-minute | 12,084 | Operational monitoring |
| 10-minute | 6,042 | Standard industry reporting |
| 1-hour | 1,008 | Long-term trend analysis |

---

## 8. Challenges Encountered

**Challenge 1 — Very high NaN rate (88%)**  
We initially expected NaN rates of 20–30% for IoT sensor data. Finding 88% was unexpected. After investigation, this appears to be because the device logs a timestamp slot for every possible reading but only sends a value when the sensor reports a change or crosses a threshold. Signals like WTUR1_TurSt_actSt are intentionally sparse — they only log on state change.

**Challenge 2 — Sampling gap calculation was mixing devices**  
The initial gap calculation (diff on all timestamps combined) showed a median gap of 0.0 seconds, which was wrong. This happened because different devices have slightly different timestamp offsets, and when all devices are combined, consecutive timestamps from different devices look like near-zero gaps. We fixed this by computing gaps per device separately.

**Challenge 3 — 5 sensors completely silent**  
WTUR1_TotWh, WTUR1_TotVArh, WTRF1_TrfTmpCell, WTRF1_TrfTmpWdg, and WROT1_RotSpd reported zero readings across all 7 days and all 6 devices. We could not determine from the data alone whether these sensors are not installed, not connected, or experiencing a software/hardware fault. This should be investigated by the field team.

**Challenge 4 — Circular direction signals**  
WNAC1_WdDir and WNAC1_Dir cannot be averaged using standard mean because compass bearings wrap around at 360°. We flagged these automatically using a data-driven test (range > 300° and values near both 0 and 360). A proper circular mean would require something beyond the current scope but recommended for future improvement.

---

## 9. Summary of Findings for the Team


88% NaN rate overall — Impact: High. This limits how much we can trust the analytics. Recommendation: investigate why the devices are logging so few real values. It may be a configuration issue where sensors only log on value change rather than at a fixed interval.

5 signals completely silent — Impact: High. WTUR1_TotWh, WTUR1_TotVArh, WTRF1_TrfTmpCell, WTRF1_TrfTmpWdg, and WROT1_RotSpd sent zero readings across all 7 days and all 6 devices. Recommendation: check sensor connectivity and hardware status in the field.

Max outage up to 79 seconds (Device6) — Impact: Medium. Every device went offline briefly at some point, with Device6 having the longest single gap at 79 seconds. Recommendation: monitor Device6 connectivity and check if it is more prone to comms dropout than the other devices.

3 signals not safe to average — Impact: Medium. WNAC1_Dir, WNAC1_WdDir (compass directions) and WTUR1_TurSt_actSt (status code) cannot be averaged using standard mean. Doing so would produce wrong or meaningless numbers. Recommendation: use Last value only for these signals in all aggregations.
