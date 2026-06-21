## 1. Running the code locally

This repository intentionally does not include the large raw dataset files in Git history, because those files are very large and would slow down pushes, clones, and code review.

To run this solution locally:

1. Download the data from: https://drive.google.com/file/d/1RC6ck7RCw8LwMdHwwmZyz08Iac8ozeTV/view?usp=drive_link

2. Place the six raw dataset files in the repository root, alongside `solution.py`:
   - `Device1_2020_07_01_00_00_02.969_2020_07_31_23_59_58.110.csv`
   - `Device2_2020_07_01_00_00_02.962_2020_07_31_23_59_55.106.csv`
   - `Device3_2020_07_01_00_00_02.961_2020_07_31_23_59_56.601.csv`
   - `Device4_2020_07_01_00_00_02.967_2020_07_31_23_59_58.103.csv`
   - `Device5_2020_07_01_00_00_05.962_2020_07_31_23_59_58.103.csv`
   - `Device6_2020_07_01_00_00_01.461_2020_07_31_23_59_56.606.csv`

3. Install dependencies:
```bash
   python -m venv venv
   source venv/bin/activate      # Windows: venv\Scripts\activate
   pip install -r requirements.txt
```

4. Run the analysis:
```bash
   python solution.py
```

> If the files are not present, `solution.py` will print an error and exit. Results are written to `./output/`.

---

## Task overview

Process raw data from edge devices — cleaning, imputing, and transforming into aggregated datasets.

---

## Question 1 — 10-minute aggregates

Process the data into 10-min aggregates for each column, including **average, min, max, last value, and standard deviation**.

**A. Data quality**
What issues should you be careful about? How do you measure data quality?

**B. Signal validity**
Are there signals for which aggregation does not make sense? Identify those signals in this dataset.

**C. NaN handling**
How would you handle NaNs? Plot scatter plot distributions of a variable before and after imputation.

**D. Timezone column**
Add a `timestamp_z` column to the 10-min aggregates holding timestamps in the `America/Los_Angeles` timezone.

**E. General aggregation function** *(optional)*
Create a reusable function that supports 1-min, 5-min, 10-min aggregates and beyond.

---

## Question 2 — Visualisation

Perform basic timeseries and scatter plot visualisation of the processed 10-min aggregate dataset, using `WNAC1_WdSpd_Avg` as the X-axis.

Example: plot 10-min average wind speed (`WNAC1_WdSpd_Avg`) against 10-min power (`WTUR1_W_Avg`).

*(Optional: provide plots at a per-device level.)*

---

## Question 3 — Containerisation *(bonus)*

Convert the solution into a Docker container or AWS Lambda function that accepts a single raw file or a list of files as input.

---

## Findings

Documented in [`observation_report.md`](./observation_report.md).