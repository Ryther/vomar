# Release a coordinated distribution

Use this runbook to prepare, review and publish one exact source/artifact set.
Release Please owns distribution `VERSION`, changelog proposals and tags.
Firmware, Android versionName/versionCode, desktop and converter retain their
independent native versions. A distribution filename does not change an embedded
version or make an older native artifact an upgrade.

Read `tools/release/manifest.py`, `evidence.py`, `assemble.py`, `publish.py` and
`.github/workflows/` when changing this contract. Configure protected settings
with [GitHub setup](github-setup.md). Never modify published tags/assets or create
replacement production signing identities.

## Choose the release route

| Route | Required physical evidence | Firmware behavior |
| --- | --- | --- |
| Qualified | Exact-source firmware report with all thirteen checks true and independent native platform evidence | Promote outer metadata only; preserve signed components/carrier. |
| Explicit accepted experimental | Dated protected owner acceptance of actual issues and unverified checks | Preserve the candidate ZIP and OTA bytes, purpose and false flags; no promotion. |

APS-105-5241 remains unresolved in this source. Software checks, signing and an
accepted publication do not qualify the firmware or establish working lights.

## Candidate and signing

1. Review the Release Please proposal and select the exact immutable source SHA.
   Read native versions from their owners in that source and compare them with
   installed versions. Do not hand-edit release-owned version/changelog state.
2. Run the reusable validation workflow for that exact SHA. Build/test jobs have
   no production signing/publication credentials. Native packages are built on
   Linux x64, Windows x64 and macOS Apple Silicon; Android produces an unsigned
   APK. DK compilation uses an ephemeral development signer.
3. Pass exact-run artifacts as data into protected signing jobs. Helpers execute
   from the protected revision. Firmware and Android signer fingerprints must
   match `tools/release/signing-identities.json`; missing/mismatched keys fail.
4. Verify the firmware candidate by exact SHA-256. Qualified promotion requires
   separately protected source/component/loader evidence with all thirteen
   literal physical flags true. Host tests cannot populate those flags.

Firmware source candidate 1.1.6 separates recovery compatibility from exact
operation identity. A common MAIN authenticates the stable RECOVERY/profile2
split-staging/journalV2/32KiB LZMA2+ARMThumb ABI without a recovery-version list.
The candidate builder validates the actual recovery configuration before
signing that profile. Breaking the ABI requires a new authenticated profile
and an explicit migration; increasing SemVer alone does not change the ABI.
Run the real-crypto multi-version pair, transport-worker and installer tests
in `tools/firmware/tests`: an admitted older recovery must remain usable after
a MAIN upgrade, and a changed in-flight recovery or loader must be rejected.
Existing artifact hashes, journals and exact installer checks retain their
meaning. No software result supplies the physical qualification below.


## Complete immutable draft

The normal set has eleven payload roles: common firmware, its exact OTA carrier,
signed APK, three native desktop archives, Windows per-user installer, converter,
notices, offline guide and dependency inventory (`source-sbom`). Alongside them,
`release-manifest.json` binds source commit, role, size, SHA-256 and native
component version; `SHA256SUMS` covers the full asset set. The accepted route
adds the owner acceptance payload, for twelve payload roles and fourteen files.

The publisher defaults to dry-run. It rejects duplicate/published releases,
wrong target/tag SHA, missing required checks, incomplete or extra assets,
nonmatching signatures and stale evidence. It requires exact-revision Sonar OK
with zero open security issues and unreviewed hotspots, plus successful current
CodeQL analyses for all five configured categories and zero open high/critical
security or error alerts. It checks mutable remote gates again immediately
before publication. Existing identical uploads are retained; differing bytes
are rejected. Complete upload/readback precedes `draft=false`.

Automatic qualified assembly uses `FIRMWARE_CANDIDATE_URL` and
`FIRMWARE_CANDIDATE_SHA256` together. Both absent means “not configured” and no
assembly; only one present is an error. `AUTO_PUBLISH_RELEASES` must remain false
until protected environments, complete evidence, a successful dry run and owner
authorization exist. Source changes require a new candidate and matching evidence.

## Explicit release with experimental firmware

This route is manual. Actions must use `workflow_dispatch`; automatic triggers
cannot select it. The candidate remains byte-identical, purpose
`qualification-candidate`, with all thirteen physical flags false. Its firmware
filenames end in `-qualification-candidate.zip` and
`-qualification-candidate.ota`. Applications retain their native versions.

Prepare new private staging paths, exact-run inputs, the signed candidate and
existing Android signing inputs. Set `DISTRIBUTION_VERSION` to the Release
Please-selected version and `CANDIDATE_SHA` to the full reviewed source SHA:

```sh
python -m tools.release.assemble --accepted-with-known-issues \
  --inputs "$RELEASE_INPUTS" --output "$STAGED_ASSETS" \
  --version "$DISTRIBUTION_VERSION" --sha "$CANDIDATE_SHA" \
  --firmware-candidate "$FIRMWARE_CANDIDATE" \
  --keystore "$ANDROID_KEYSTORE" --password-file "$ANDROID_PASSWORD_FILE" \
  --android-tools "$ANDROID_TOOLS"
```

Staging creates eleven payloads plus manifest/checksums. It validates the signed
candidate, signs/audits the APK and compares firmware with the exact exported
`firmware/VERSION`. It creates no acceptance and authorizes no publication.

Review the actual files before collecting protected owner acceptance. The strict
schema in `owner_acceptance()` requires schema1, kind
`accepted-with-known-issues`, `sourceCommit`, `distributionVersion`, UTC
`acceptedAt` within fourteen days, `acceptedBy`, a statement and the eleven
payload role/hash bindings. `knownIssues` discloses unresolved APS-105-5241 with
impact/evidence. `firmwarePurpose` stays `qualification-candidate`; every
`firmwareChecks` and per-platform `nativeChecks` value stays literal false.
Risk acceptance must never claim an unperformed test passed.

After the owner accepts those exact bytes:

```sh
python -m tools.release.assemble --finalize-accepted "$STAGED_ASSETS" \
  --acceptance "$OWNER_ACCEPTANCE"
```

This copies the acceptance document unchanged as `release-acceptance`, refreshes
manifest/checksums and does not rebuild payloads. Changed payload or approval
bytes require a new reviewed stage. Prepare dependency review for all twelve
final roles, then verify with independently available acceptance bytes:

```sh
python -m tools.release.publish --directory "$STAGED_ASSETS" \
  --accepted-with-known-issues --acceptance "$OWNER_ACCEPTANCE" \
  --dependency-review "$DEPENDENCY_REVIEW" \
  --public-key firmware/keys/dev-public.pem --android-tools "$ANDROID_TOOLS"
```

Dry-run uploads nothing. The final explicitly authorized publication adds
`--publish` in the protected context and rechecks the same gates. The draft body
must contain this exact sentence, required by the publisher:

```text
Experimental firmware: APS-105-5241 remains unresolved; firmware and native physical qualification checks are unverified.
```

For hosted review use **Publish accepted experimental distribution**
(`publish-accepted.yml`) on `main`. Pin the Release Please draft and tag to the
reviewed source SHA, upload the fourteen frozen files and configure protected
`OWNER_ACCEPTANCE_JSON`/`DEPENDENCY_REVIEW_JSON`. Dispatch `sha`, the selected
`version` and `publish=false`; review success before separately authorizing
`publish=true`. This workflow downloads/verifies existing files and performs no
build or promotion. A draft asset need not be publicly downloadable to stage it.

Android may announce project-release availability with **Experimental** and a
release-notes action. Metadata discovery never selects candidate firmware or
starts an operation. Normal catalogue admission rejects experimental firmware;
use the explicit manual candidate path and fresh device review. Desktop retains
its explicit Bluetooth trial route. The acceptance asset is no device-write
permission and does not make its OTA carrier eligible for automatic selection.

## Evidence and limits

Credentialed analysis uses protected settings/helpers with candidate source as
data. Every covered language requires actual matching compilation/coverage
reports. PR Python/JavaScript/Kotlin Sonar and firmware CodeQL checks do not
replace full protected main/release Sonar including C compilation/coverage.
Fork/Dependabot analysis uses a disposable instance without reusable secrets.

Firmware qualification must include the full forty-character `sourceCommit`
and exact component/loader bindings, collected with build provenance. Neither
passing host tests nor the existence of a workflow establishes physical evidence,
remote settings, Pages deployment or signer custody.

## Delivered dependencies and native qualification

`source-sbom` contains actual Gradle release runtime inventory, the complete
frozen Nordic SDK graph and each native bundle's dependency closure, shipped-file
and artifact hashes. CI advisory queries are mandatory and query failures fail.
Automated OSV/npm checks do not cover every Qt/OpenOCD/system/Nordic binary.

Protected `DEPENDENCY_REVIEW_JSON` binds source, every final artifact, every
inventory graph and a UTC review date within fourteen days. Record vendor
advisory review with explicit dispositions and reproducible evidence. Missing
scope, stale review or unresolved software advisories blocks publication. Use
`fixed` or demonstrated `not-affected`; do not suppress an advisory in CI just
to obtain a green check. Unreachable vulnerable APIs can justify `not-affected`
with an input-path analysis; that does not mean the library is fixed.

The accepted route has one bounded physical-risk exception: Nordic SA-2025-380,
covering nRF52840 CC310 AES confidentiality under precisely timed physical voltage
fault injection. Review the original advisory and actual physical threat model.
It is not a fix, fault-injection qualification or waiver of remote/software
security review. Only `firmware-sdk` may use
`reviewed-with-accepted-physical-risk`, with one `accepted-physical-risk`
disposition for that exact ID. Public owner acceptance must disclose the same ID
as unresolved with exactly matching `impact` and `evidence`. Both documents still
bind source/hashes/dates. Qualified publication rejects this exception.

`NATIVE_QUALIFICATION_JSON` independently binds Linux x64, Windows x64 and macOS
arm64 assets (including both Windows packages) and real observations for
`filesystemTransactions`, `bluetoothPermissionsAndUpdate`,
`dkDriverInstallRepairStart` and `stopAndRestartRecovery`. Each platform needs its
own bench reference. Hosted smoke builds cannot populate these fields. The
qualified route requires firmware and native evidence even in dry-run; the
accepted route instead discloses false native/firmware checks and retains the
same dependency review. Shapes and fictional examples live in `evidence.py` and
`tools/release/tests/test_protected_evidence.py`; never submit fixture evidence
for a release. Keep actual private bench records outside public source.

## Android version discovery in Obtainium

Publication names the release `Vomar bundle BUNDLE · Android NATIVE_VERSION` using
the Android version from the independently verified `release-manifest.json`.
Obtainium's import configuration selects the release title, extracts only the
Android version and compares it with the installed APK using OS version detection.
A firmware-only bundle therefore does not appear as an Android app update. The
tag, asset filenames and Release Please distribution owner remain unchanged.
Keep this title metadata when editing release notes; do not substitute the bundle
version for Android's version. Published APK bytes and signing identity stay immutable.
