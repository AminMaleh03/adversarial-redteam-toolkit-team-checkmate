# Robustness report

The report consumes historical schema-v2 or target-aware schema-v3
[analysis JSON](../analysis/README.md), renders an
offline HTML report with Jinja2, and exports an A4 PDF with WeasyPrint. It does not load
the classifier, import another component, rescore attacks, or infer finding resolution.

Schema v3 renders each target independently, shows a comparison only for a valid paired
evaluation, and explains why a single-target comparison is null. Core evaluations require
coverage evidence; OCES evaluations require their frozen additional-evaluation block. Every
new finding must carry observed evidence, significance, diagnosis confidence, a specific
fix, and a runnable target-aware verification route. Missing required evidence fails
validation instead of producing an empty successful panel.

## Generate a report

From the repository root, using the project's Python 3.11 `.venv`:

```powershell
.\.venv\Scripts\python.exe -m report.generate --input results/analysis_remediation/report_input.json --out results/checkmate-report
```

`--out` must name a **new** directory. Existing evidence is never overwritten. Choose
a new directory for each export. All generated artifacts belong under ignored `results/`.

The saved benchmark is `results/full_20260909_135157`; generated results are not in Git.
To analyze that benchmark and render directly without a shell-created intermediate file:

```powershell
$env:PYTHONIOENCODING = "utf-8"
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
.\.venv\Scripts\python.exe -m analysis.analyze results/full_20260909_135157 | .\.venv\Scripts\python.exe -m report.generate --input - --out results/checkmate-report-fresh
```

On macOS/Linux, use `.venv/bin/python` in place of the Windows executable. The UTF-8
PowerShell settings avoid Windows PowerShell 5.1's default ASCII pipeline encoding.
An upstream analysis failure produces no usable JSON, so report generation fails too.

For HTML without the native PDF runtime:

```powershell
.\.venv\Scripts\python.exe -m report.generate --input results/analysis_remediation/report_input.json --out results/checkmate-html --html-only
```

HTML-only mode does not import WeasyPrint. PDF output needs the existing WeasyPrint
runtime on Ahsan's machine. `requirements.txt` pins `pydyf==0.10.0` because WeasyPrint
62.3 uses the older stream API; newer pydyf releases removed deprecated methods
([upstream changelog](https://doc.courtbouillon.org/pydyf/latest/changelog.html)).

## Output bundle

| File | Purpose |
| --- | --- |
| `report.html` | Browser report with internal navigation and expandable evidence |
| `report.pdf` | Full printable report, including expanded evidence; omitted with `--html-only` |
| `analysis.json` | Exact input bytes, preserved for audit and download |
| `export_meta.json` | Report/schema versions and SHA-256 hashes of the input and outputs |

Open `report.html` in a browser. No server, JavaScript, network assets or model is needed.
Keep the bundle together so its download links work. PDF links to report sections are
internal; use the sibling files for JSON/export metadata. PDF bytes can vary by installed
fonts or rendering libraries; HTML is deterministic for the same input and report source.
The export hash identifies the analysis JSON, not the original benchmark implementation
commit. Keep original JSONL, manifests, run metadata and provenance alongside the bundle.

## Interpretation

- The top summary uses structured finding comparisons, including improved and unavailable
  case IDs. It never substitutes the legacy convenience lists.
- `unavailable` is displayed as **inconclusive**. A remaining group can also have improved
  and inconclusive original cases; these qualifications stay attached to the group.
- Demonstrated new and inconclusive new evidence can share a group key. Their case IDs
  remain disjoint; the report states the distinct group count to avoid double counting.
- The presence of `comparison_withheld_reason` suppresses comparison conclusions even if
  stale comparison fields coexist. Independent version observations remain visible.
- Coverage accompanies comparisons. Empty/partial runs are explicitly labeled. Category
  rates and flip rates retain their own denominators; a zero denominator stays `N/A`.
- Severity uses the supplied tier. Scores just below a tier boundary display a bound such
  as `<60 / Medium`, avoiding a rounded `60 / Medium` contradiction.
- SILVER evidence is explicitly qualified. REVIEW and diagnostic cases appear in the
  audit sections and never become scored findings. Mixed diagnostic oracle/tier entries
  retain the recorded tier difference.
- Request errors and observed health unavailability are separate. The report never infers
  process death or the server stage that caused a timeout.

Input validation checks consumed field types, counts/rates, coverage partitions, finding
joins and comparison evidence consistency. It does not independently reconstruct the
manifest or establish whether an analyst's judgment was correct. Unrecognized extra
fields are ignored; unsupported schema versions are rejected.

## Safety and failures

All analysis strings are autoescaped, including titles, remediation and evidence IDs.
Only the repository-owned stylesheet is inserted as trusted HTML. The report has no
scripts, uses a restrictive content security policy, and the PDF renderer denies all
resource fetching (including local-file URLs).

The CLI exits 0 on success, 1 on input/render/output failure and 2 for invalid arguments.
Validation and PDF rendering finish before the output directory is created. A filesystem
failure during publication can leave a partial new directory; the command reports failure.
Keep that directory for diagnosis and use a fresh destination after resolving the error.

## Master technical report (V6.3+)

`report/master_report.py` renders the multi-target master technical report served at
`/technical-report/`, combining the historical emotion.core benchmark with real
sentiment.core, emotion.oces, sentiment.oces and ci.emotion evidence into one navigable
document. It never re-scores or re-runs an evaluation -- it only reads already-recorded
evidence, listed with its SHA-256 in `report/master_evidence/manifest.json`.

```powershell
.\.venv\Scripts\python.exe -m report.master_report
```

This re-hashes every file the manifest lists and refuses to render (exit 1) if any is
missing or its bytes no longer match -- evidence integrity fails closed, not silently.
Output is committed at `artifacts/technical_report/` (the same pattern as
`artifacts/verified_full_report/`): pre-generated, never regenerated on request by the
web app. `web/app.py` mounts it at `/technical-report/` alongside the archived
`/verified-full/` route, which the master report links to as historical evidence and
never overwrites.

To add a new evidence source: run it for real, commit the resulting bundle under
`artifacts/<name>/` with its own `PROVENANCE.md`, add its path and SHA-256 to
`report/master_evidence/manifest.json`, then extend `master_report.build_context` and
`master_template.html` to read it. Never hand-edit a bundle's bytes after generation, and
never point the manifest at a path under gitignored `results/`.

## Validate

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_report.py -q
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

Tests cover malformed input, withheld comparisons, partial coverage, rate denominators,
evidence qualifications, severity boundaries, HTML escaping, output preservation, CLI
file/stdin modes, and actual PDF generation with full printed evidence. The PDF test
skips only when the native renderer cannot import; it is required to pass on Ahsan's
report-generation environment. A final visual review should inspect desktop/mobile HTML,
PDF page breaks, long IDs, tables, and internal links using the agreed saved benchmark.
