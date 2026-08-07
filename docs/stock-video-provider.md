# Licensed stock-video provider

Vistora can acquire real supporting footage through its existing confirmed
material-production boundary. Pexels is queried first and Pixabay is used only
when the primary source is unavailable or has no matching candidate. Nothing
is placed on the timeline automatically.

## Configuration

Keep credentials outside Git and project JSON:

```text
PEXELS_API_KEY=...
PIXABAY_API_KEY=...
```

An optional `<project-stem>.stock-video-provider.json` sidecar controls cache
location, limits, provider priority and credential environment-variable names.
It must never contain a credential value. Example:

```json
{
  "schema_name": "vistora.stock-video-provider",
  "schema_version": "1.0.0",
  "cache_root": "E:/VistoraData/stock-video-cache",
  "request_timeout_seconds": 30,
  "max_download_bytes": 536870912,
  "search_cache_hours": 24,
  "max_candidates_per_task": 1,
  "require_non_system_drive": true,
  "sources": [
    {
      "provider_id": "pexels",
      "api_key_env": "PEXELS_API_KEY",
      "enabled": true,
      "priority": 1
    },
    {
      "provider_id": "pixabay",
      "api_key_env": "PIXABAY_API_KEY",
      "enabled": true,
      "priority": 2
    }
  ]
}
```

Without a sidecar, Vistora activates the provider only when at least one key is
present and uses a project-relative cache. On Windows the production default
rejects a system-drive cache; projects on the system drive should provide an
explicit sidecar pointing to a non-system drive.

## Confirmed task parameters

An `asset_search` / `library_search` task can bind these ordered
`reproducibility_parameters`:

- `material_provider_adapter_id=stock_video_library`
- `stock_query=<editorial search phrase>`
- `stock_provider=auto|pexels|pixabay`
- `stock_orientation=any|landscape|portrait|square`
- `stock_asset_id=<exact provider asset ID>` (optional)
- `stock_max_candidates=1..3` (optional, bounded by configuration)

The adapter uses HTTPS allowlists, bounded API responses and downloads, a
24-hour metadata cache, and create-new staging files. API keys never enter the
registry, ledger, browser view, log message or cache.

## Review, licence and ingest

Every downloaded candidate remains staged until normal Vistora media
validation succeeds and a user explicitly accepts it. Candidate and catalog
views include provider, asset ID, source page, creator, licence URL,
attribution state, restrictions, retrieval time and a tamper-evident digest.
The direct file URL is represented only by a SHA-256 digest in public
provenance.

Accepted footage then uses the existing O24 path: full decode, normalized
transcode, bounded proxy, technical analysis, tags, quality checks and atomic
catalog registration. Rejected footage never enters the catalog, and no stock
candidate can bypass Director review and EditingAgent confirmation to mutate a
timeline.

Provider terms still apply to each use. Vistora records evidence and
restrictions but does not provide legal clearance for depicted people,
trademarks, property or editorial context.
