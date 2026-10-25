# Reverse Engineering Rules

For each important finding, record:

- source artifact;
- address/file path;
- relevant function address;
- supporting strings/XREFs;
- callers/callees when useful;
- evidence classification;
- remaining uncertainty.

Prefer reproducible scripts, Ghidra headless analysis, call graphs, and
string-XREF reports over repeated manual GUI operations.

Original evidence under `inputs/` is immutable.

For a derived binary:

1. copy/read from the original;
2. write the derived artifact outside `inputs/`;
3. record the original SHA-256;
4. record exactly what changed.

Read-only debugging/passive observation precedes hardware writes.
