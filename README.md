# LogLens — Desktop and command-line log analysis

LogLens turns a structured application log into a failure dashboard and a searchable record explorer, with a streaming CLI for scripts.

- Find failing services, recurring messages, severity counts, and the UTC time range.
- Search the entire file and inspect the original message behind a table row.
- Save filter presets and export an offline HTML report, JSON summary, or selected records.

![LogLens dashboard for the fulfillment sample, showing 184 valid records and 26 failures](assets/desktop-dashboard.png)

The included fulfillment log has **186 lines, 2 malformed records, and 26 failures among 184 valid records (14.13%)**. The desktop uses Python 3.11+, Qt model/view, and SQLite. The standard-library CLI shares its streaming parser, UTC handling, and report format with the desktop.

## Quick start on Windows

From a checkout of the redesign branch, run these PowerShell commands:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[gui]"
.\.venv\Scripts\loglens-gui.exe examples/fulfillment.log
```

To open an empty workspace, omit the filename. The equivalent module command is `.\.venv\Scripts\python.exe -m loglens.gui`. On macOS or Linux with a graphical session, create the environment with `python3 -m venv .venv`, install with `.venv/bin/python -m pip install ".[gui]"`, and run `.venv/bin/loglens-gui examples/fulfillment.log`.

For a CLI-only installation, use `python -m pip install .` in your environment. The CLI also runs directly from the checkout:

```console
python -m loglens examples/checkout.log
```

## Using the desktop

1. **Open a file.** Use **Open file**, drag in one local `.log` or `.txt` file, or choose a recent file. Hover over the filename to see its path. Refresh rereads the source. The progress bar measures bytes read and switches to a busy indicator while SQLite prepares the index. Cancelling a replacement scan keeps the last successful analysis available.
2. **Read the dashboard.** **Entire file** covers all valid records. **Explorer matches** shows the applied search and filters. Lines read, valid, and malformed always describe the input. Failure percentage uses the matched record count. The time chart divides the selected UTC range into 20 equal intervals and shows both record and failure counts.
3. **Investigate a record.** In **Log explorer**, type to search across complete messages. **Match case** switches from Unicode case-folded search to exact case. Open **Filters** to combine severity, comma-separated exact service names, and inclusive timestamp bounds. Choose **Apply filters**, or **Clear** to start again. Save a named preset to reuse the combination. The applied-filter caption and match count describe the displayed results.
4. **Browse every match.** Click a heading for a global sort, use the page selector to jump, or choose 50–500 rows per page. Severity sorts from DEBUG through CRITICAL. Ties retain input order. Cells preview up to 512 characters. Select a row to inspect its source line, UTC timestamp, severity, service and complete message. Longer text is readable in 8,192-character parts.
5. **Export findings.** The header **Export** menu offers entire-file and explorer-match summaries as JSON or self-contained HTML. Select one or more rows on a page and choose **Export selected** for UTF-8 JSON Lines. Each line contains `line` (one-based source line), `timestamp` (UTC), `level`, `service`, and the complete `message`. The inspector also copies the record as JSON or just its original message.

![Log explorer with ERROR and CRITICAL selected and a source record open in the inspector](assets/desktop-explorer.png)

**Keyboard.** Ctrl+O opens a file, Ctrl+F focuses message search, Ctrl+R refreshes, and Esc cancels active work. Ctrl+C in the table copies the current record. Text fields retain normal copy behavior.

**Appearance and layout.** Settings offers dark, light, or system colors, font size, table density, visible columns, and 1–100 ranked results. Drag headers to reorder or resize columns and drag the inspector divider to allocate space. Narrow windows place the inspector below the table. Choose pixel or row scrolling. Auto reduces transitions after slow animation ticks. Reduced motion or Off disables transitions. [Compact light-theme screenshot](assets/desktop-compact-light.png)

**Saved workspace.** Settings, geometry, filter presets, last-used filters, and up to ten recent paths are saved locally. The footer reports pending changes, successful saves, or a write failure. Windows uses `%LOCALAPPDATA%\LogLens\desktop.json`. Other platforms use `$XDG_CONFIG_HOME/LogLens/desktop.json` or `~/.config/LogLens/desktop.json`. These settings can contain filenames and search text. Use Settings to clear recent paths or reset the workspace. A damaged or newer-format settings file is preserved until a confirmed reset.

## Input format

Each physical line is one UTF-8 record:

```text
2026-01-15T10:00:04+01:00 | ERROR | payments | Upstream timeout
```

| Field | Accepted values |
| --- | --- |
| Timestamp | `YYYY-MM-DDTHH:MM:SS`, optional 1–6 fractional digits, then `Z` or a signed `HH:MM` offset. Dates and offsets must be valid and convertible to UTC. |
| Severity | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`, uppercase in the file. |
| Service | An ASCII letter or digit followed by any number of ASCII letters, digits, underscores, periods, or hyphens. Case-sensitive. |
| Message | Nonblank text. Spaces and additional field delimiters within the message are preserved. |

The separator is a space, a vertical bar, and a space. LF, CRLF, an optional initial UTF-8 BOM, and a final line without a newline are supported. A blank line, malformed record, or line with invalid UTF-8 contributes one rejection reason. Processing continues at the next physical line. The [sample logs](examples/) contain synthetic data.

## CLI examples

```console
python -m loglens --help
python -m loglens examples/checkout.log --search timeout --format json
python -m loglens examples/checkout.log --level error --level critical --service payments
python -m loglens examples/checkout.log --since 2026-01-15T09:00:02Z --until 2026-01-15T09:00:06Z --top 2
python -m loglens examples/worker.log --format json -o worker.json
python -m loglens examples/checkout.log --format html -o checkout.html
```

Open `checkout.html` in a browser to view the [HTML report example](assets/checkout-report.png). It works offline. Repeated levels or services select any listed value in that category. All supplied categories must match. Time bounds include both endpoints and compare UTC instants. Records can arrive out of order.

## Example output

The checkout sample has 10 lines. One line is malformed. Of the 9 valid records, 4 are failures (44.44%). The terminal ranking reads:

```text
Top failing services
  payments  3
  inventory  1

Top error messages
  Upstream timeout  2
  Circuit open  1
  Rejected SKU <trial> & queued retry  1
```

| Report field | Interpretation |
| --- | --- |
| Lines read | Matched + filtered out + malformed. Rejections are counted before filtering. |
| Failures / failure rate | Matched `ERROR` and `CRITICAL` records, and their percentage of all matched records. An empty selection has a JSON rate of `null`. |
| Earliest / latest UTC | Minimum and maximum timestamps among matched records. Both are `null` for an empty selection. |
| Top failing services | Services ranked by number of matched failures. |
| Top error messages | Exact failure message frequencies across selected services, including singletons. |

Both rankings default to five entries. Ties use ascending, case-sensitive string order. An output file is written as UTF-8 and replaced after a successful write. Its parent directory must exist. Reports go to stdout by default. Exit code `0` means the scan completed, including scans with rejected lines. File or output errors return `1`, and invalid CLI arguments return `2`.

## Tests and benchmark

```console
python -m unittest discover -s tests -v
python -m benchmarks.streaming --rows 100000 --runs 5
```

Install the GUI extra to include the Qt interaction tests locally. GitHub Actions installs the extra and runs the suite and an installed-command smoke test on Windows and Linux with Python 3.11 and 3.14. Tests cover parsing, filtering, UTC boundaries, ranking ties, damaged UTF-8, HTML escaping, and output-file replacement.

The following CLI baseline was measured with LogLens 0.1.0. Two independent invocations of the streaming benchmark ran on Windows 11 (build 26300), CPython 3.12.14. Each generated 100,000 records (6,838,205 bytes) across seven services, with an error every tenth record and 31 distinct failure messages.

| Invocation | Five scan times (seconds) | Median rows/s | Peak traced bytes |
| --- | --- | ---: | ---: |
| 1 | 0.231248, 0.222719, 0.229224, 0.262454, 0.223478 | 436,255 | 15,656 |
| 2 | 0.228270, 0.221584, 0.221057, 0.220314, 0.228005 | 451,295 | 15,656 |

Each timed scan opens the file, parses and aggregates it, and checks the row and error totals. Timings exclude dataset generation and report rendering. Throughput divides the row count by the median elapsed time. A separate sixth scan measures Python allocations with `tracemalloc`. Interpreter startup, native allocations outside the tracer, and OS file caches are excluded. These figures describe this synthetic workload. Disk cache state, CPU load, line length, and the number of distinct messages can all affect results.

### Desktop measurements

Run `python -m benchmarks.desktop --rows 250000` in the GUI environment. Add `--unique` for one distinct error message per record. See the [desktop benchmark results](docs/desktop-performance.md) for measured scan time, search latency, paint intervals, event-loop gaps, process memory, and database size across six Windows workloads.

## Project layout

```text
loglens/                  Parser, filters, aggregation, renderers, desktop and CLI
examples/                 Synthetic checkout, worker, and fulfillment inputs
tests/                    Unit and subprocess integration tests
benchmarks/               CLI throughput and live desktop benchmarks
docs/architecture.md      Data flow, complexity, failure handling, and limits
.github/workflows/ci.yml  Windows and Linux test matrix
pyproject.toml            Package metadata and console entry point
```

See the [architecture notes](docs/architecture.md) for design decisions and scaling limits.

## Limitations and future work

LogLens accepts one file with one record per physical line. A single record must fit in memory. The CLI keeps exact failure-key counters in RAM. The desktop stores all valid records in a local temporary SQLite database and requires disk space for the active snapshot, a replacement snapshot during refresh, and SQLite temporary work. Large sorts and deep pages can take longer. The snapshot is removed on normal close. A forced process termination can leave temporary files.

Refresh to see changes after a scan. Rotated-log aggregation and multiline stack traces are possible future extensions.

## License

Copyright © 2026 Aadarsha Hiremath. Distributed under the [MIT License](LICENSE).
