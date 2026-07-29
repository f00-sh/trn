# trn

Enhanced Tabular Recipe Notation (eTRN) converter — Cooking for Engineers style process matrices

Keep this README in sync with the man page(s) under [man/](man/) and the
GitHub Pages site under [docs/](docs/).

## Requirements

- Python (version: document the supported toolchain)

## Install

Every install method installs man page(s). Prefer the curl path from releases.

### Curl (releases)

```text
curl -fsSL https://github.com/f00-sh/trn/releases/latest/download/install.sh | sh
```

### Package managers

Document only channels this project maintains (creator chooses among Arch/AUR, Homebrew, RPM, deb). Remove unused sections.

```text
# Arch / AUR (if offered):
# yay -S trn

# Homebrew (if offered):
# brew install f00-sh/tap/trn

# RPM (if offered):
# sudo rpm -Uvh trn-VERSION.rpm

# deb (if offered):
# sudo dpkg -i trn_VERSION_amd64.deb
```

### From source

```text
# Language-native or make install when useful for developers.
# cargo install --path .
# go install ./cmd/trn@latest
```

## Usage

```text
# Show the common commands a new user needs first.
```

Full option reference: see [man/trn.1.md](man/trn.1.md).

## Configuration

Document flags, environment variables, and config files.
Provide a `.env.example` when environment variables are required. Never commit real secrets.

## Documentation

| Surface | Location |
|---|---|
| This README | [README.md](README.md) |
| Man page(s) | [man/](man/) |
| GitHub Pages | [docs/](docs/) |
| Changelog | [CHANGELOG.md](CHANGELOG.md) |
| Scene card | [file_id.diz](file_id.diz) |

## Scene card

Each SemVer release ships a crafted `file_id.diz` (ACiD / 16colo.rs-style block ASCII
archive card) next to the changelog notes. Keep this preview identical to root
[file_id.diz](file_id.diz). GitHub Releases attach the same file as an asset.

```text
╔══════════════════════════════════════════════════╗
║▓▓▓▓░░░░  trn  ░░░░▓▓▓▓              ║
║████████████████████████████████████████████████  ║
║  ▄█▀  SCENE CARD  ▀█▄   release identity         ║
║████████████████████████████████████████████████  ║
║  v0.0.0  ·  MIT  ·  2026                     ║
║  Enhanced Tabular Recipe Notation (eTRN) converter — Cooking for Engineers style process matrices                         ║
║  github:f00-sh/trn          ║
╚══════════════════════════════════════════════════╝
```

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md).

```text
# Format, test, and build commands for this language
```

## Versioning

This project uses [Semantic Versioning](https://semver.org/). See [CHANGELOG.md](CHANGELOG.md).
Every published version also refreshes [file_id.diz](file_id.diz) and attaches it to the GitHub Release.

## Security

See [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © f00
