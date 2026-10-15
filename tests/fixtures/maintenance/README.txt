Maintenance fixtures.

Every file here is synthetic or explicitly labelled as reconstructed. No file
contains a captured production response body, a live cache entry, a webhook
token or any other secret.

  python_manifest_*.json   setup-python release manifests (candidate selection)
  release_dates_*.json     tag -> ISO release date maps (soak policy)
  run_report_*.json        monitor run reports (renderer counters/redaction)
  persistence_*.json       cache save/commit/push records (footer states)
  merge_*.json             merge-controller decision payloads (no-write mode)
  crosspost_*.json         sanitized child/original/proxy records for the
                           2026-10-15 AnantaLeaks_1x6h1mf crosspost incident.
                           These are SYNTHETIC reconstructions of the identity
                           and metadata shapes described in the incident, not
                           captured RSS/archive/proxy responses.
  production_layout.json   the documentation-free production copy manifest
