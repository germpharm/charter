# Changelog

## [1.5.0] - 2026-02-22

### Added
- Expanded Marketplace discoverability — 30 keywords, Machine Learning category
- Improved README with compliance templates and feature details

## [1.4.0] - 2026-02-22

### Fixed
- Status bar hidden when no folder is open (no false UNGOVERNED on blank windows)
- Retry logic when workspace folders load after activation

## [1.3.0] - 2026-02-22

### Fixed
- Workspace folder availability race condition at activation

## [1.2.0] - 2026-02-22

### Fixed
- PATH resolution for Charter CLI in extension host
- Async race condition between governance check and daemon polling

### Added
- Diagnostic logging to Output channel

## [1.1.0] - 2026-02-22

### Added
- Auto-bootstrap: ungoverned workspaces automatically get governance files
- Extended PATH search for Python/pip binary locations

## [1.0.0] - 2026-02-22

### Added
- Initial release
- Status bar governance indicator (GOVERNED / UNGOVERNED)
- Daemon health monitoring
- File system watcher for charter.yaml
- Configuration settings for daemon port, poll interval, auto-bootstrap
