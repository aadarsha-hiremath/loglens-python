# Architecture

## One file, one pass

1. `cli.main` validates arguments, including the order of the timestamp bounds. It opens the input in binary mode and passes the file iterator to `analyze`. Both `python -m loglens` and the installed console command call this function.
2. `parsing.parse_line` decodes one physical line at a time. Local decoding lets a damaged byte invalidate only its own record. A split limited to the first three delimiters preserves the free-text message. The parser returns an immutable, slotted `Record` or raises `RecordError` with a fixed diagnostic category.
3. `analysis.Filters` compares a record against two sets and up to two UTC instants. The analyzer increments the rejection counter before applying filters. Each matched record updates severity counts and time extrema. Failures also update counters keyed by service and exact message.
4. `reporting.render` derives report totals and selects the top entries. Each output format shares the same denominators and ranking rules. JSON uses ordered arrays for rankings. The text and HTML renderers display controls as escape sequences. The HTML renderer uses `html.escape` for dynamic cells and embeds all styling.
5. For file output, the CLI closes a temporary file in the destination directory before calling `os.replace`. A failed write or replacement leaves the previous report intact. A same-file check rejects input/output aliases, including existing hard links. Diagnostic messages go to stderr.

The analysis accepts an iterable that yields one physical line as bytes per iteration. Unit tests can feed it single-pass iterators. Integration tests invoke the module in a separate Python process and assert exit codes, stdout, stderr, and file contents.

## Reading the counts

Every physical line belongs to exactly one group: malformed, filtered out, or matched. Only matched records contribute to the time range, severity counts, and failure rate. For example, filtering the checkout sample to `payments` gives 1 malformed line, 6 filtered out, and 3 matched. All 3 matched records are failures, so the filtered failure rate is 100%. With zero matches the rate is undefined and JSON represents it as `null`.

## Complexity

Let **B** be input bytes, **L** the longest physical line, **S** the number of distinct matched failing services, **E** the number of distinct matched failure messages, and **K** the ranking limit.

| Operation | Time | Working memory |
| --- | --- | --- |
| Decode, parse, filter, aggregate | Expected O(B), including string hashing and decoding | O(L) transient space plus stored counters, their distinct keys, and user-supplied filters |
| Update minimum and maximum time | O(1) per matched record | O(1) |
| Select top K from D keys (`D = S` or `E`) | O(D log(1 + min(K, D))) comparisons | O(min(K, D)) entries |
| Format a report | O(formatted output length) after selection | O(formatted output length) |

Hash table lookups and updates take expected constant time once keys are hashed. Counters store O(S + E) entries and the text of each distinct key. Comparing strings to break a ranking tie can inspect their common prefix. `heapq.nsmallest` ranks by negative count then key, and can sort the whole collection when all entries are requested.

## Limits of this release

- Input is a single file in the documented format. Multiline stack traces and rotated files require preprocessing.
- A single very long physical line must fit in memory. Exact grouping can also use substantial memory when messages contain unique request IDs. Lowering `--top` limits output size while all distinct failure keys are still counted.
- Counts measure failure volume. A high-traffic service can lead the ranking even if its own failure percentage is low.
- UTC normalization supports years 1 through 9999. Leap seconds and zone names are outside the timestamp grammar.
