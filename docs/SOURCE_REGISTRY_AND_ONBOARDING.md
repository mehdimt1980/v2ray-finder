# Source Registry

The source registry is the runtime contract between the external source hunter and the native Android app.

`v2ray-finder` no longer performs global source discovery. Discovery, crawling, scoring and registry generation are handled outside this repository. This repository consumes the resulting trusted registry and uses it for native Android fetching, validation and source-performance reporting.

## Active file

```text
registry/sources.json
```

This is the only source registry consumed by the default native Android scan path.

## Runtime flow

```text
registry/sources.json
→ native Android registry loader
→ concurrent source fetch
→ config extraction
→ early source-balanced sampling
→ native TCP health checks
→ optional native xray validation
→ source performance report
```

## Source statuses

| Status | Meaning | Used in default scan? |
|---|---|---|
| `official` | Maintained/approved source | yes |
| `trusted` | Performs well enough to be active | yes |
| `candidate` | Under review | only if enabled in the registry |
| `disabled` | Kept for reference | no |

The Android app only uses sources that are enabled in `registry/sources.json`.
