# Coordinated distribution release

Distribution VERSION begins at 0.0.0. Release Please proposes its first version
from Conventional Commits and creates drafts with vMAJOR.MINOR.PATCH tags.
Firmware, Android versionName/versionCode, desktop and converter versions are
independent native owners; no release step resets them to the distribution tag.

## Candidate and signing

Validate one full immutable source SHA through the reusable workflow. Build/test
jobs receive no production signing, publication or Sonar token. Native packages
are built on all four runner architectures; Android emits an unsigned APK.
Public DK compilation uses an explicit ephemeral development signer and cannot
produce official firmware. Source and generated caches are separate.

A protected signer job downloads exact-run artifacts as data and runs helpers
from the protected workflow revision. It receives the **existing** firmware key
and Android keystore only through protected inputs. Their public fingerprints
are pinned in tools/release/signing-identities.json. Missing/mismatched identities
fail; official identities are never generated automatically.

A signed firmware qualification candidate is downloaded by exact SHA-256 and
verified. Promotion requires a separately protected report with all thirteen
literal physical checks true, exact component hashes and loader contracts.
It preserves component/loader/carrier bytes and signs qualified outer metadata.
The current 1.0.0 candidate has every physical flag false, so promotion and stable
publication must fail. Host, GUI and hosted-runner tests cannot fill those flags.

## Complete immutable draft

The assembler requires common firmware, its exact OTA carrier, signed APK, four
native desktop packages, Windows per-user installer, converter, notices and the
offline guide. release-manifest.json schema1 records roles, sizes, hashes,
component versions and the source commit. SHA256SUMS covers the full asset set.

The publisher defaults to dry-run. It discovers the exact draft, rejects duplicate
or already published releases, requires immutable target/tag SHA and successful
stable checks, then checks Sonar's exact revision, OK quality status, zero open
security issues and zero unreviewed hotspots. It rechecks mutable remote gates
before publication. Existing identical uploads are retained; differing bytes or
unreviewed extra assets fail. Upload completeness/readback precedes draft=false.
A source fix creates a new reviewed candidate; never overwrite published bytes.

Use the release workflow in dry-run mode before enabling publication. The workflow runs automatically after successful main validation, using the
protected FIRMWARE_CANDIDATE_URL and SHA256 variables. Manual exact-candidate
dry runs remain available. AUTO_PUBLISH_RELEASES enables the final publication
step only after exact physical evidence and protected environments are configured.

## Evidence and limits

Credentialed Sonar analysis uses protected settings/helpers and candidate source
as data. Every language needs its actual reports. Missing coverage, target
compilation, extraction scope or current analysis fails the gate. Fork/Dependabot
must not receive reusable Cloud/signing/release credentials; local community
analysis has explicit language limitations and cannot substitute an unsupported
C/Kotlin analyzer for full release analysis.

Repository workflows are configuration, not evidence that GitHub protections,
credentials, Pages or Sonar are live. Configure and inspect them through the
[GitHub setup guide](github-setup.md). Native BLE/USB and physical qualification
are separate recorded checks per platform/probe/target.

The protected qualification JSON must also include `sourceCommit` with the full
40-character distribution source commit. This is an operator attestation linking
the measured binaries to the reviewed source; it must be collected with the
exact build provenance, never inferred from a passing host test. Assembly and
publication reject evidence from another commit. The loader contracts and every
role image hash remain bound by the signed common package.
