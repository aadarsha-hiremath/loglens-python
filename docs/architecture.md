# Architecture

## CLI data flow

1. `cli.main` validates arguments, including the order of the timestamp bounds. It opens the input in binary mode and passes the file iterator to `analyze`. Both `python -m loglens` and the installed console command call this function.
2. `parsing.parse_line` decodes one physical line at a time. Local decoding lets a damaged byte invalidate only its own record. A split limited to the first three delimiters preserves the free-text message. The parser returns an immutable, slotted `Record` or raises `RecordError` with a fixed diagnostic category.
3. `analysis.Filters` compares a record against two sets and up to two UTC instants, plus an optional case-folded message substring. The analyzer increments the rejection counter before applying filters. Each matched record updates severity counts and time extrema. Failures also update counters keyed by service and exact message.
4. `reporting.render` derives report totals and selects the top entries. Each output format shares the same denominators and ranking rules. JSON uses ordered arrays for rankings. The text and HTML renderers display controls as escape sequences. The HTML renderer uses `html.escape` for dynamic cells and embeds all styling.
5. For file output, the CLI closes a temporary file in the destination directory before calling `os.replace`. A failed write or replacement leaves the previous report intact. A same-file check rejects input/output aliases, including existing hard links. Diagnostic messages go to stderr.

The analysis accepts an iterable that yields one physical line as bytes per iteration. Unit tests can feed it single-pass iterators. Integration tests invoke the module in a separate Python process and assert exit codes, stdout, stderr, and file contents.

## Reading the counts

Every physical line belongs to exactly one group: malformed, filtered out, or matched. Only matched records contribute to the time range, severity counts, and failure rate. For example, filtering the checkout sample to `payments` gives 1 malformed line, 6 filtered out, and 3 matched. All 3 matched records are failures, so the filtered failure rate is 100%. With zero matches the rate is undefined and JSON represents it as `null`.

## CLI complexity

Let **B** be input bytes, **L** the longest physical line, **S** the number of distinct matched failing services, **E** the number of distinct matched failure messages, and **K** the ranking limit.

| Operation | Time | Working memory |
| --- | --- | --- |
| Decode, parse, filter, aggregate | Expected O(B), including string hashing and decoding | O(L) transient space plus stored counters, their distinct keys, and user-supplied filters |
| Update minimum and maximum time | O(1) per matched record | O(1) |
| Select top K from D keys (`D = S` or `E`) | O(D log(1 + min(K, D))) comparisons | O(min(K, D)) entries |
| Format a report | O(formatted output length) after selection | O(formatted output length) |

Hash table lookups and updates take expected constant time once keys are hashed. Counters store O(S + E) entries and the text of each distinct key. Comparing strings to break a ranking tie can inspect their common prefix. `heapq.nsmallest` ranks by negative count then key, and can sort the whole collection when all entries are requested.

## Desktop snapshots and queries

The optional `loglens.gui` entry point loads Qt. The CLI entry point imports only the standard library. `desktop_data` streams the same `matching_records` iterator as the CLI, preserves physical line numbers, and updates a shared `Summary`. It writes each valid record and its case-folded message into temporary SQLite storage. Fixed-width UTC strings order timestamps chronologically. Signed microseconds preserve exact offsets when grouping the chart into 20 equal-duration intervals.

The snapshot indexes timestamp, severity, and service. Search uses a parameterized literal substring predicate over the original or case-folded message. It can inspect all message bytes. A scoped query groups by severity and obtains extrema; two additional queries group failures by service and exact message with the CLI's deterministic tie-break. Only the first 100 ranked keys return to Python. Both dashboard scopes and both report exporters use the shared report schema. The database can reuse the full summary and timeline when the scope is empty.

`explorer.Rows` is a Qt table model over one page. Sorting applies to all matches before the page limit and offset, with source line number as the stable tie-break. The widget holds at most 500 rows and previews at most 512 characters per cell. A second worker retrieves the selected original record. The inspector displays long values in 8,192-character parts. Selected JSONL export streams records to a temporary sibling file, then replaces the destination.

## Concurrency and state

`desktop_jobs.Jobs` runs a serial executor and delivers values through a thread-safe queue that Qt drains on the GUI thread. Each request has a generation and cancellation event. The parser checks cancellation per physical line and SQLite uses a progress handler. An old result cannot replace a newer search, page, or file. A separate serial reader handles inspection. The workspace publishes the new file, report, and page together after all three are ready. Refresh builds a separate candidate database so the previous analysis stays usable on failure. The scanner checks source identity, size, and modification time. Closing joins both workers before deleting the temporary directory.

The window applies palette, scaling, and geometry to native controls. Charts draw a fixed number of severity categories and time buckets. The rankings use a bounded item view. The explorer changes splitter orientation at narrow widths. Brief navigation transitions stop when superseded. Auto skips transitions during work or after slow animation ticks. Preferences debounce ordinary saves and use atomic JSON replacement. Compatible settings migrate field by field; unreadable or unrecognized documents are protected from automatic replacement.

## Desktop complexity

For N valid records, storing the snapshot takes space proportional to their text and indexes. Index creation and global sorting can take O(N log N) comparisons. A literal substring filter can scan the entire snapshot. Grouping or sorting may use file-backed SQLite temporary storage. An offset page may revisit its predecessors. The SQLite page-cache target is 2 MiB per connection. Python keeps a bounded number of page rows, ranked keys, chart bins, and one inspected record. A single very long record or failure key can still increase process memory. Measured costs are in [desktop performance](desktop-performance.md).

## Limits of this release

- Input is a single file in the documented format. Multiline stack traces and rotated files require preprocessing.
- A single very long physical line must fit in memory. The CLI's exact grouping can also use substantial memory when messages contain unique request IDs. Lowering `--top` limits output size while all distinct failure keys are still counted.
- Counts measure failure volume. A high-traffic service can lead the ranking even if its own failure percentage is low.
- UTC normalization supports years 1 through 9999. Leap seconds and zone names are outside the timestamp grammar.
