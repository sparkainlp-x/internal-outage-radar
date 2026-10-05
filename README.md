# Internal Outage Radar (offline prototype)

[![tests](https://github.com/sparkainlp-x/internal-outage-radar/actions/workflows/tests.yml/badge.svg)](https://github.com/sparkainlp-x/internal-outage-radar/actions/workflows/tests.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23057994.svg)](https://doi.org/10.5281/zenodo.23057994)
[![Status: research prototype](https://img.shields.io/badge/status-research%20prototype-orange.svg)](#before-using-a-real-production-monitor)
[![Evidence: SYNTHETIC](https://img.shields.io/badge/evidence-SYNTHETIC-blue.svg)](#before-using-a-real-production-monitor)

Internal Outage Radar correlates your organization's own service-check results from
multiple vantage sites. It helps answer "is this failure broad, isolated to one site, or
aligned with a declared dependency?" without treating a correlation as proof of a root
cause. It is an offline analyzer of a saved JSON snapshot — not a public outage map,
network scanner, probe runner, or live monitor.

The prototype uses only Python's standard library (3.10+). It makes no network requests,
contacts no hosts or services, stores no credentials, and does not deploy or schedule
anything. The included data is synthetic. (A test checks that the module imports only a
small allowlist of offline standard-library modules.)

## Quickstart

From the repository root:

```bash
python3 -m py_compile outage_radar.py tests/test_outage_radar.py
python3 -m unittest discover -s tests -v
python3 outage_radar.py --input examples/sample_input.json --output examples/sample_output.json
```

Omit `--output` to print formatted JSON to standard output:

```bash
python3 outage_radar.py --input examples/sample_input.json
```

The CLI exits with status 2 and writes an error to standard error (and writes no output
file) for unreadable, non-UTF-8 or malformed JSON input and for schema violations. It
rejects duplicate JSON object keys, `NaN`/`Infinity` constants, unexpected or missing
fields, duplicate checks, unknown site/service/dependency references, invalid statuses,
and invalid quorum or timestamp values. A check row may be absent or have status
`unknown`; those cases are reported separately and are not counted as usable results.

## Input snapshot

The supported schema is version 1 (`"schema_version": 1`). A snapshot contains:

- `observed_at`: timezone-aware ISO 8601 time for the snapshot (e.g. `2026-09-30T09:15:00Z`).
- `sites`: unique vantage-site IDs.
- `minimum_quorum_sites`: integer from 2 through the number of sites. A usable result is a
  check whose status is `ok` or `fail`; `unknown` and absent checks do not count toward quorum.
- `services`: unique service IDs and their declared dependency IDs. Use an empty
  dependency list when none are known.
- `service_checks`: zero or one `{site, service, status}` row per site/service pair.
- `dependency_checks`: zero or one `{site, dependency, status}` row per declared
  dependency/site pair.
- `status`: exactly `ok`, `fail`, or `unknown`.

`examples/sample_input.json` is a complete synthetic example. It intentionally includes a
single-site failure, a multi-site service failure, a dependency co-failure, missing/unknown
probes, and a healthy service. The format represents an already collected snapshot; the
program itself does not perform checks.

## Classification logic

For each declared service, the analyzer reports sorted evidence lists for failed, healthy,
unknown, and missing service checks; the usable-site count; and whether quorum was met. It
also lists the same coverage details for each declared dependency, including the sites
where the dependency and the service both failed.

Classification precedence is deterministic:

1. **dependency-wide** — a declared dependency and the service fail at the same sites, in at
   least the configured quorum of sites.
2. **likely service-wide** — service failures occur at or above the site quorum, without a
   qualifying dependency co-failure.
3. **site-local/connectivity-path** — exactly one site reports failure, at least one other site
   reports success, and usable results meet quorum.
4. **no observed failure** — no service failures are present and usable results meet quorum.
   This extra outcome avoids labeling a healthy snapshot as an outage or as an evidence failure.
5. **insufficient evidence/unknown** — none of the patterns above is supported. This includes
   too few usable sites and non-quorum failures spread across several sites.

These are scope signals, not diagnoses. In particular, *dependency-wide* means declared
dependency failures overlap with service failures; it does not establish that the dependency
caused the service failures. *Site-local/connectivity-path* does not distinguish a local
probe, site, network path, or other site-specific problem. Partial coverage is surfaced
explicitly rather than silently treated as success. Thresholds are not calibrated against
any real system.

## Deterministic output

`examples/sample_output.json` is generated from `examples/sample_input.json` by the
quickstart command. Output uses stable sorting, is independent of input ordering, and
contains no generated-at clock value. The test suite checks that the CLI reproduces the
committed file byte-for-byte and pins its SHA-256
(`77e3bf4bfb67db478950a27a78383ce1d05014f47dfda31c5d84997a70fb60ff`); a deliberate change to
the output format must update the pinned hash (and `schema_version` if the format changes).

## Tests

The `unittest` suite (17 tests, run in CI on Python 3.10–3.13) covers every classification,
dependency overlap (including below-quorum overlap and undeclared dependencies), missing and
unknown probes, quorum edge cases, stable output across input ordering, strict
malformed-input rejection, duplicate JSON keys, `NaN` constants, non-UTF-8 input, missing
input files, reproduction of the committed sample output with a pinned hash, and the
offline-imports check.

## Before using a real production monitor

This prototype does not collect, validate, or authenticate probes. A production system
would still need an authorized probe/agent design for owned services; secure and reliable
multi-site execution; health-check definitions and dependency ownership; time windows,
retries, stale-data handling, and calibrated per-service quorum thresholds; storage, access
controls, secrets handling, retention, and auditability; alert routing, deduplication,
escalation, and operator runbooks; deployment, upgrades, availability, monitoring of the
monitor, and incident-safe failure modes; and privacy/security review. It would also need
historical baselines and operational validation to tune thresholds and limit false positives.
None of those capabilities is implemented or implied here.

## Citation

See [CITATION.cff](CITATION.cff).

## License

This software is available under the GNU Affero General Public License v3.0 only (AGPL-3.0-only); see [LICENSE](LICENSE).

Organizations that want to use it in proprietary products or services without AGPL obligations can contact the author about a commercial license via https://sparkainlpx.xyz.
