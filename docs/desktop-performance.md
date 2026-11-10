# Desktop performance

These measurements used the native Windows Qt window with the default theme and animations, Windows 11 build 26300, CPython 3.12.14, and PySide6 6.12.0. Each row is one fresh process. Generate the same inputs from the repository root after installing the GUI extra:

```powershell
foreach ($rows in 10000,100000,250000) {
    python -m benchmarks.desktop --rows $rows
    python -m benchmarks.desktop --rows $rows --unique
}
```

## Opening and searching

| Records | Error messages | Open through first page (s) | Search through first page (ms) | Peak working set (MiB) | Snapshot (MiB) |
| ---: | --- | ---: | ---: | ---: | ---: |
| 10,000 | Repeated | 0.109 | 31 | 141.1 | 1.67 |
| 10,000 | Unique | 0.094 | 20 | 140.8 | 1.67 |
| 100,000 | Repeated | 0.697 | 102 | 142.5 | 16.91 |
| 100,000 | Unique | 0.753 | 106 | 126.7 | 16.91 |
| 250,000 | Repeated | 1.703 | 248 | 139.5 | 42.41 |
| 250,000 | Unique | 1.721 | 243 | 143.0 | 42.41 |

The generator cycles through seven services and two message prefixes. Every record is an error. Repeated workloads have six distinct messages, and unique workloads have one per row. Open time includes streaming, SQLite insertion and indexing, exact statistics, and first-page delivery to the open window. Search applies the literal substring `Retry` to the existing snapshot, checks that half the rows match, recomputes the scoped statistics, and loads a 500-row page. Both timings exclude application startup and data generation.

Peak working set comes from Windows `GetProcessMemoryInfo` and includes Python, Qt, and SQLite. Snapshot size measures the completed database. Temporary sort files or two overlapping snapshots during refresh can require more disk space.

## Event-loop and table paint intervals

| Records | Messages | Longest gap opening (ms) | Table paint median / max (ms) | Longest gap navigating (ms) | Estimated missed scroll slots |
| ---: | --- | ---: | ---: | ---: | ---: |
| 10,000 | Repeated | 19.4 | 16.0 / 17.3 | 24.4 | 0 |
| 10,000 | Unique | 18.8 | 16.0 / 17.4 | 22.3 | 0 |
| 100,000 | Repeated | 23.6 | 15.9 / 18.2 | 23.5 | 0 |
| 100,000 | Unique | 18.3 | 16.0 / 17.4 | 22.4 | 0 |
| 250,000 | Repeated | 23.0 | 16.0 / 17.4 | 23.8 | 0 |
| 250,000 | Unique | 24.1 | 15.8 / 19.8 | 21.5 | 0 |

A precise Qt timer samples the GUI event loop every 16 ms. During scrolling a second timer moves the table scrollbar by 13 pixels for each of 120 ticks, while an event filter records paints on the table viewport. Navigation alternates between the dashboard and explorer eight times. Each JSON benchmark result includes event counts, intervals above two 60 Hz periods, and an estimate of missed slots computed as the sum of `max(0, round(interval / (1/60)) - 1)`. These are event and paint timings. Display presentation and GPU frame delivery were outside the measurement.

During development, first displaying the dashboard at the end of a scan produced a 179.9 ms dispatch gap in the 10,000-row repeated case. Profiling isolated that delay to first showing the stacked dashboard widget. The dashboard now initializes with the window and displays file-opening instructions inline. The final six runs above had no opening, scrolling, or navigation intervals above 33.3 ms. Input length, hardware, file caching, display scale, and concurrent workloads can change these results.
