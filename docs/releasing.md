# Coordinated distribution release

Distribution VERSION begins at 0.0.0. Release Please proposes its first version
from Conventional Commits and creates drafts with vMAJOR.MINOR.PATCH tags.
Firmware, Android versionName/versionCode, desktop and converter versions are
independent native owners; no release step resets them to the distribution tag.

The planned first official distribution is **2.0.0**. Put `Release-As: 2.0.0`
in the actual integration squash commit body on main, then review the generated
Release Please proposal. The footer must survive the squash; a PR comment alone
cannot select the release version. Release Please continues to own `VERSION`,
the release manifest state, changelog and tag. Do not hand-edit those files.

Distribution filenames use 2.0.0 while embedded native versions remain independent.
For example, a distribution can contain firmware 1.1.2, Android 1.1.3/code33,
desktop 1.1.1 and converter 1.0.1. This example does not qualify those binaries
for publication. Android upgrade ordering uses its monotonically increasing
versionCode; signed firmware admission uses the firmware identity and version,
never the distribution tag. Compare each native candidate with the installed
versions before qualification; calling the distribution 2.0.0 cannot make an older
native image an upgrade.

The distribution manifest requires all four component owners and binds every
artifact's componentVersion to its owner. Notices, guide and inventory use the
distribution version. Desktop packaging verifies frozen CLI output, Windows
installer/executable version resources and both macOS bundle version fields
against the native desktop owner before writing a successful package report.

## Candidate and signing

Validate one full immutable source SHA through the reusable workflow. Build/test
jobs receive no production signing, publication or Sonar token. Native packages
are built for Linux x64, Windows x64 and macOS Apple Silicon (arm64); Android
emits an unsigned APK. Intel Mac packages are not currently required or produced.
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
A candidate with any physical flag false cannot be promoted or published as
qualified firmware. Host, GUI and hosted-runner tests cannot fill those flags.
The explicit accepted route below can distribute that unchanged experimental
candidate alongside the official applications; it does not qualify the firmware.

## Complete immutable draft

The assembler requires common firmware, its exact OTA carrier, signed APK, three
native desktop archives, the Windows per-user installer, converter, notices and
the offline guide plus the complete dependency inventory archive (eleven artifact
roles, release-manifest.json and SHA256SUMS). release-manifest.json schema1 records roles, sizes, hashes,
component versions and the source commit. SHA256SUMS covers the full asset set.

The publisher defaults to dry-run. It discovers the exact draft, rejects duplicate
or already published releases, requires immutable target/tag SHA and successful
stable checks, then checks Sonar's exact revision, OK quality status, zero open
security issues and zero unreviewed hotspots. It rechecks mutable remote gates
before publication. Existing identical uploads are retained; differing bytes or
unreviewed extra assets fail. Upload completeness/readback precedes draft=false.
A source fix creates a new reviewed candidate; never overwrite published bytes.

Use the release workflow in dry-run mode before enabling publication. After
successful main validation, automatic assembly uses the repository variables
`FIRMWARE_CANDIDATE_URL` and `FIRMWARE_CANDIDATE_SHA256`. When both are absent,
the resolver records that assembly is not configured and downstream jobs skip;
no assets are assembled or published. A partially configured pair, malformed
values or an incomplete manual request fails with a named configuration error.
Manual exact-candidate dry runs remain available. `AUTO_PUBLISH_RELEASES` enables
the final publication step only after exact physical evidence and protected
environments are configured. A successful unconfigured resolver is not a release
or qualification result.

## Explicit release with experimental firmware

An official application distribution may include experimental firmware after
the owner accepts its actual known issues and unverified physical checks.
For the planned 2.0.0 release, the known firmware issue is **APS-105-5241**:
the Zigbee stack can assert and restart. Its cause remains unresolved. An
accepted distribution is not an overall physical qualification statement.
The standard qualified route above remains unchanged.

This route is manual only. In GitHub Actions it requires `workflow_dispatch`;
automatic main/release triggers cannot select it. It never invokes firmware
promotion. The signed ZIP remains byte-identical with purpose
`qualification-candidate`, all thirteen physical flags false and the existing
signer. Its two firmware filenames end in `-qualification-candidate.zip` and
`-qualification-candidate.ota`. Application filenames and embedded native
versions remain independent of firmware qualification.

Stage the actual signed payloads before requesting final acceptance. Use exact
candidate-run downloads and a local signed candidate ZIP; this does not require
a draft asset to be publicly downloadable. Set the following variables to the
reviewed source SHA, paths and existing Android signing identity, then run in
the pinned development environment:

```sh
python -m tools.release.assemble --accepted-with-known-issues \
  --inputs "$RELEASE_INPUTS" --output "$STAGED_ASSETS" \
  --version 2.0.0 --sha "$CANDIDATE_SHA" \
  --firmware-candidate "$FIRMWARE_CANDIDATE" \
  --keystore "$ANDROID_KEYSTORE" --password-file "$ANDROID_PASSWORD_FILE" \
  --android-tools "$ANDROID_TOOLS"
```

Staging writes eleven payloads, `release-manifest.json` and `SHA256SUMS`.
It validates the signed candidate, signs/audits the APK and checks the firmware
version against `firmware/VERSION` exported from the exact source. It creates
no owner acceptance and grants no publication authority.

Review those concrete files, then prepare a separate protected owner acceptance
JSON. `owner_acceptance` in `tools/release/evidence.py` defines its strict schema;
the fictional tests are examples of shape only, never release evidence. The
document requires schema1, kind `accepted-with-known-issues`, `sourceCommit`,
`distributionVersion`, a UTC `acceptedAt` within fourteen days, `acceptedBy`,
an explicit `statement`, and `artifacts` mapping all eleven payload roles to
their actual SHA-256 values. `knownIssues` must disclose unresolved
`APS-105-5241` with its impact and evidence. `firmwarePurpose` remains
`qualification-candidate`; every `firmwareChecks` value and every platform's
`nativeChecks` value remains literal false. Do not claim a test happened merely
because its risk was accepted. Native checks use the four names and three
platforms described below.

Finalise only after the owner has accepted that exact artifact set:

```sh
python -m tools.release.assemble --finalize-accepted "$STAGED_ASSETS" \
  --acceptance "$OWNER_ACCEPTANCE"
```

This adds `vomar-release-acceptance-2.0.0.json` unchanged as role
`release-acceptance`, then refreshes the manifest/checksums. The complete set is
twelve payload roles and fourteen files. Acceptance binds the eleven other
payload hashes; the manifest and checksums bind acceptance itself. Payloads are
not rebuilt or changed. Changed approval or payload bytes require a new stage.

Prepare the protected dependency review against this final twelve-role manifest,
including the acceptance artifact and all five delivered inventory graphs.
Then independently verify locally:

```sh
python -m tools.release.publish --directory "$STAGED_ASSETS" \
  --accepted-with-known-issues --acceptance "$OWNER_ACCEPTANCE" \
  --dependency-review "$DEPENDENCY_REVIEW" \
  --public-key firmware/keys/dev-public.pem --android-tools "$ANDROID_TOOLS"
```

Missing/mismatched acceptance or advisory review fails. APK/firmware signature
continuity, exact source checks, Sonar/security requirements and immutable upload
readback still apply. The final authorised publication adds `--publish` in the
protected publication context; dry-run alone uploads nothing. Release notes must
identify official applications and experimental firmware, the unresolved assert
and the unverified native checks. Do not call the firmware qualified.
The publisher requires this exact sentence in the draft body and rechecks it
immediately before publication:

```text
Experimental firmware: APS-105-5241 remains unresolved; firmware and native physical qualification checks are unverified.
```

All release assets remain individually downloadable. Android and desktop
firmware catalogues recognise this distribution but refuse automatic firmware
admission with **Firmware is experimental; import ZIP through Bluetooth trial**.
Use the explicit existing manual trial path and fresh device-operation review;
the acceptance file does not authorise a device write. The experimental OTA
carrier is not automatically selected from the normal firmware catalogue.

For protected hosted verification/publication, use the separate manual
**Publish accepted experimental distribution** workflow on `main`. First pin
the Release Please draft and tag to the exact final source SHA and upload the
fourteen already frozen files. Configure `OWNER_ACCEPTANCE_JSON` and
`DEPENDENCY_REVIEW_JSON` in `release-publication`, then dispatch with `sha`,
`version=2.0.0` and `publish=false`. It authenticates private-draft downloads,
verifies the same bytes and performs no rebuild. A later explicitly authorised
`publish=true` dispatch rechecks the complete candidate and mutable publication
gates. See [GitHub setup](github-setup.md#retain-existing-signing-identities-and-qualification)
for the exact credentials and preparation. Automatic qualified assembly remains
a separate route.

## Evidence and limits

Credentialed Sonar analysis uses protected settings/helpers and candidate source
as data. Every language needs its actual reports. Missing coverage, target
compilation, extraction scope or current analysis fails the gate. Fork/Dependabot
must not receive reusable Cloud/signing/release credentials. PR Community
analysis covers Python, JavaScript and Kotlin; its complete findings and
baseline comparison are published as artifacts. Firmware C has the separate
mandatory CodeQL check. The PR result cannot replace the full protected
main/release Sonar analysis with actual C compilation/coverage.

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

## Delivered dependencies and native qualification

Every distribution includes `source-sbom`: a ZIP of the actual Gradle release
runtime inventory, the complete pinned public Nordic SDK graph, and each native
bundle's runtime package closure, shipped-file hashes and artifact hashes.
Android/SDK OSV queries, per-platform Python/native inventory queries and the
assistant npm audit are mandatory CI checks. A query failure fails validation.
OSV does not cover every Qt, OpenOCD, system-library or Nordic/ZBOSS vendor binary.

`DEPENDENCY_REVIEW_JSON` therefore records a separately protected advisory review
of every delivered inventory graph. It binds the source commit, every release
artifact hash, every inventory hash, a UTC review date within fourteen days, and
explicit evidence/dispositions. Missing scope, stale evidence or unresolved
advisories keep publication blocked. Inspect vendor advisories and the exact
bundled files for unsupported automated scopes; an empty OSV response is not
proof of full coverage. A confirmed advisory must be fixed or receive a protected
`not-affected` disposition with reproducible evidence. Never ignore it in a CI
allowlist to obtain a green result.

The manual accepted experimental route has one explicit hardware-risk exception:
Nordic **SA-2025-380** concerns nRF52840 CC310 AES confidentiality under precisely
timed voltage fault injection with physical access and dedicated equipment. The
hardware is not claimed fixed or resistant to that attack, and no fault-injection
qualification is implied. Review the [original Nordic advisory](https://docs-be.nordicsemi.com/bundle/SA/raw/resource/enus/SA-2025-380-v1_0.pdf)
against the product's physical threat model. This exception does not admit any
other advisory, software defect or remote attack.

Only `firmware-sdk` may use graph status
`reviewed-with-accepted-physical-risk`. It must contain one disposition with
`id: SA-2025-380`, `status: accepted-physical-risk`, and descriptive `impact` and
`evidence` strings. The protected `OWNER_ACCEPTANCE_JSON` and its byte-identical
published asset must include that same ID as an `unresolved` known issue with
exactly matching `impact` and `evidence`. Both dated documents still bind the exact
source and all required artifact/inventory hashes. The publisher admits this
assessment only with the explicit manual accepted mode and validated public
owner acceptance. The qualified route rejects it; all other advisories still
require `fixed` or evidence-backed `not-affected` dispositions. An affected
component whose vulnerable API is unreachable in this product can be assessed as
`not-affected` with a reproducible input-path review; do not call its library fixed.

`NATIVE_QUALIFICATION_JSON` is separate from firmware qualification. For Linux
x64, Windows x64 and macOS Apple Silicon (arm64) it binds exact native asset hashes
(including both Windows packages) and literal true observations for:
`filesystemTransactions`, `bluetoothPermissionsAndUpdate`,
`dkDriverInstallRepairStart` and `stopAndRestartRecovery`. Each platform entry
requires an independent bench evidence reference. Build smoke checks cannot
populate these fields. The qualified publisher requires both protected JSON
documents even for a local dry run; the accepted experimental route instead
requires protected owner acceptance disclosing unverified native checks plus the
same dependency review. Their strict shapes are implemented in
`tools/release/evidence.py` and demonstrated with fictional test data in
`tools/release/tests/test_protected_evidence.py`. Do not reuse synthetic test data
as release evidence. Store actual evidence outside the public source tree.
