# GitHub setup

Configure `Ryther/vomar` through repository settings or an authenticated `gh`
with repository administration access. Workflow files alone do not enforce
GitHub settings. Use this runbook with a fresh remote inspection; the private
local audit records which steps have actually been applied.

## Protect the development branch

Use `main` as the default branch and keep Actions enabled. Use read-only default
workflow permissions; individual trusted jobs declare their additional access.
The proposal credential creates release PRs, so the built-in token does not need
permission to approve PR reviews.

Require pull requests, current-base checks, linear history and conversation
resolution. Enforce protection for administrators, prohibit force pushes and
branch deletion. Squash using the PR title so Conventional Commit release
semantics survive merging; delete merged branches. Both reference repositories
require a PR with zero mandatory approving reviews, allowing a sole maintainer
to merge after checks. Requiring a second person's approval is a separate policy
choice, not a prerequisite for this setup.

Read the actual `pullRequest` contexts from
[the required-check policy](https://github.com/Ryther/vomar/blob/main/.github/required-checks.json).
Bind them to the GitHub Actions app. GitHub prefixes a reusable workflow's check
with its caller: the PR context is **`sonar-pr / Sonar required`**. The protected
main/release check is **`Sonar required`**. Requiring the main context on PRs would
leave them waiting for a check that is not produced there.

Establish the reviewed infrastructure on the trusted base before enforcing new
PR checks. Inspect actual check runs for an ordinary same-repository PR and a
fork/Dependabot PR, including scan reports, before requiring the PR Sonar context.
Until that verification, keep the other thirteen observed checks required and
record Sonar enforcement as pending. Failed required checks block merging; do not
disable them to work around runner or product failures. Allow auto-merge only
after the full required-check policy is verified; it does not approve arbitrary
updates by itself.

Infrastructure PRs execute report helpers from their protected base. Candidate
helper improvements, including complete JSON/identity exports for failed gates,
take effect after the reviewed baseline is merged. A bootstrap PR can therefore
retain the older base's early failure behavior; scanner logs and task receipts
remain available and a failed gate still fails the check. Never execute candidate
helpers with reusable credentials to work around that boundary.

Enable Dependabot vulnerability alerts, secret scanning, push protection and
private vulnerability reporting. Keep the tracked advanced CodeQL workflow;
do not replace it with GitHub's generated default setup. Verify successful
extraction and uploaded analyses for all configured languages. An API response
saying there are no analyses is not proof that code scanning is disabled.

If an upload reports that code scanning is not enabled, inspect **Settings →
Advanced Security → CodeQL analysis** as the repository owner. Retain the
existing advanced workflow rather than generating a default setup. Check the
actual UI state if feature APIs reject an enable request; do not interpret a
missing analysis as a requirement to purchase a private-repository plan for this
public project.

## Create protected environments

Create these environments with a custom deployment branch policy allowing only
branch `main`, with no tag policy or administrator bypass:

| Environment | Approval | Secrets | Variables |
| --- | --- | --- | --- |
| `release-proposal` | Automatic | `RELEASE_PROPOSAL_TOKEN` | None |
| `release-signing` | Maintainer required | `FIRMWARE_SIGNING_KEY_PEM`, `ANDROID_SIGNING_KEYSTORE_BASE64`, `ANDROID_SIGNING_PASSWORD` | `FIRMWARE_QUALIFICATION_JSON` |
| `release-publication` | Maintainer required | `VOMAR_RELEASE_PUBLICATION_TOKEN`, `SONAR_TOKEN` | `FIRMWARE_QUALIFICATION_JSON`, `NATIVE_QUALIFICATION_JSON`, `DEPENDENCY_REVIEW_JSON` |
| `sonar-analysis` | Automatic | `SONAR_TOKEN` | None |
| `github-pages` | Automatic | None | None |

For a sole maintainer, allow self-review of environment deployments so the
maintainer can approve their own requested release. This is an explicit manual
approval gate, not a requirement for a second person. With additional release
owners, review whether preventing self-review is appropriate. See
[GitHub environment protection](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).

Restrict changes to workflow files and treat every pending signing/publication
approval as a review of the exact workflow revision and candidate. A branch
policy alone does not restrict an environment to one particular workflow file.

## Configure automatic assembly

Set repository variables `FIRMWARE_CANDIDATE_URL` and
`FIRMWARE_CANDIDATE_SHA256` together when the exact signed candidate is ready.
Without both variables, an automatic run after main validation records
"not configured" and skips assembly. It produces no release assets. Setting
only one variable is a configuration error, rather than a successful skip.
Manual requests require complete valid inputs. Repository firmware defaults are reserved for automatic runs. Configuring a URL and hash does
not waive signing continuity, physical qualification or publication checks.

## Provide project credentials

These values are missing until a credential owner supplies them. GitHub returns
secret names and timestamps, never reusable plaintext values. Do not copy
credentials from either example project or use a local CLI login as a CI secret.
Create separate fine-grained tokens restricted to `Ryther/vomar`:

- `RELEASE_PROPOSAL_TOKEN`: Contents, Pull requests and Issues read/write. Store
  it only in `release-proposal`. It lets Release Please proposals trigger CI.
- `VOMAR_RELEASE_PUBLICATION_TOKEN`: Contents read/write, with Metadata
  read. Store it only in `release-publication`. It reads exact candidate checks
  and manages draft assets/tags and publication. It does not need repository
  administration or workflow editing permissions.

Check inspection uses the workflow's built-in `GITHUB_TOKEN`, passed as
`GH_CHECKS_TOKEN` with explicit Checks read permission; the owner creates no
additional secret for it. Without that optional reader credential, the publisher
reads public check runs anonymously. A failed read or missing required result
still blocks publication. The publication PAT is never sent to the Checks API.

Create project-scoped Sonar credentials for the following distinct uses:

- Repository Actions secret `SONAR_TOKEN`: trusted same-repository PR analysis,
  with project analysis and Browse access needed for complete report export.
- `sonar-analysis` environment `SONAR_TOKEN`: protected main analysis and report
  inspection.
- `release-publication` environment `SONAR_TOKEN`: read-only project Browse
  access for the exact-revision quality/security gate; it need not analyze code.

Configure public SonarQube Cloud project **`Ryther_vomar`**, organization
**`ryther`**. If the project already exists but is inaccessible, fix its access
instead of creating a duplicate. Disable automatic analysis when using CI scans,
set an explicit quality gate and confirm the project's actual plan/analyzers
support Kotlin, Python, JavaScript, firmware C and pull request analysis.
The trusted main scan installs the protected `sonar-project.properties` in the
candidate analysis root before using `projectBaseDir`. It replaces a candidate
symlink rather than following it. An explicit relative `project.settings` path
is resolved from the scanner launch directory, rather than the selected project
root. Install the protected file at the actual root instead of relying on that
path being rebased by `projectBaseDir`.

Initialize and verify a real `main` baseline. Fork/Dependabot analysis uses a
disposable Community instance without any reusable project credential; firmware
C remains mandatory in CodeQL and in full protected main/release Sonar analysis.
Missing tokens, coverage, extraction or scan reports must fail.

SonarCloud can provision a project during its first analysis when the token's
user has **Create Projects** permission and the scan has no branch/PR parameters,
including parameters inferred by CI. An initial 404 alone does not establish
that manual creation is required. Verify the first trusted-main analysis before
requesting manual setup; a first PR scan may not provision the project. Project
creation also does not establish the GitHub binding or the intended settings.
See [Sonar's provisioning conditions](https://community.sonarsource.com/t/new-project-creation-v2-apis/132494/5).

Enter secrets in GitHub's environment/repository **Secrets** UI, or pass their
contents to authenticated `gh secret set` through standard input. Do not put
values in command arguments, Git, screenshots or audit reports. From the current
workspace, the authenticated helper can receive a private file without copying
it into its container, for example:

```sh
docker exec -i hapatchy-gh-cli gh secret set RELEASE_PROPOSAL_TOKEN \
  --repo Ryther/vomar --env release-proposal < /absolute/private/proposal-token
```

Replace the example path with a protected local file. Never upload a placeholder.

## Retain existing signing identities and qualification

The credential owner must supply the **existing** firmware PEM private key,
base64-encoded Android keystore and its existing password to `release-signing`.
Check their public fingerprints against
[the pinned identities](https://github.com/Ryther/vomar/blob/main/tools/release/signing-identities.json)
before use. Do not generate replacement production identities during setup.

Set repository variables `FIRMWARE_CANDIDATE_URL` and
`FIRMWARE_CANDIDATE_SHA256` only for the exact signed candidate. The URL must meet
the workflow's GitHub HTTPS constraint. Keep `AUTO_PUBLISH_RELEASES=false` until
a complete successful dry run and owner authorization.

Provide independently reviewed `FIRMWARE_QUALIFICATION_JSON` to both signing and
publication environments. It binds the exact source/component bytes and all
thirteen real physical checks. Supply `NATIVE_QUALIFICATION_JSON` and
`DEPENDENCY_REVIEW_JSON` in `release-publication` after the exact artifacts exist.
Follow the [evidence contracts](releasing.md#delivered-dependencies-and-native-qualification).
CI results cannot fill physical checks. Linux-only bench access does not qualify
macOS/Windows hardware behavior; missing platform evidence remains a release
blocker even when hosted builds succeed.

## Enable documentation and immutable releases

Configure Pages with GitHub Actions as its source and restrict `github-pages`
to `main`. Repository variable `ENABLE_PAGES=true` opts into the existing deploy
job. Verify the next authorized Pages run and the deployed URL; creating Pages
settings does not deploy a site. Enforce HTTPS once GitHub has provisioned the
certificate; a newly created site can reject that setting until then.

Enable immutable releases before the first publication. This applies to future
published releases and does not prevent completing a draft. See
[GitHub release immutability](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/establish-provenance-and-integrity/prevent-release-changes).

After owner credentials are configured, verify a trusted PR and a
Dependabot/fork PR, enforce the final PR Sonar context, then run an exact-candidate
release dry run. Review remote settings and check results again before enabling
automatic publication. Release Please owns versions/tags; `0.0.0` is the bootstrap
manifest, not an already qualified published distribution.
