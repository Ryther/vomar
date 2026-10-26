# GitHub setup

Complete local review before pushing. No tool here changes repository visibility,
branch settings, remote secrets, tags or published releases automatically.

- Protect main and require review plus the `pullRequest` checks listed in
  [.github/required-checks.json](https://github.com/Ryther/vomar/blob/main/.github/required-checks.json).
  They are produced for PR candidates, including the aggregate CodeQL lane.
  `Sonar required` is now required for PRs as well as releases, with different
  scopes: PR Python/JavaScript/Kotlin analysis plus mandatory firmware CodeQL;
  protected main/release Sonar additionally analyzes firmware C. Inspect actual
  check runs for a normal PR and a fork/Dependabot PR before enabling the rule.
- Establish the reviewed infrastructure on the trusted base before enforcing
  its new PR checks. Scanner settings/exporters come from that base; the first
  bootstrap PR cannot supply token-bearing helpers from its own untrusted code.
- Set repository `SONAR_TOKEN` to a least-privilege PR analysis credential for
  trusted same-repository Cloud scans, including the project Browse permission
  needed to export findings. Never grant it to fork/Dependabot runs.
  The protected main/release token remains in its dedicated environment.
  Keep automatic Sonar analysis disabled when using these CI scans; initialize
  the main baseline and verify PR analysis support and required language
  analyzers on the actual project.
- Use separate protected environments: release-proposal, release-signing,
  release-publication and sonar-analysis. Restrict them to the protected default
  branch/workflow and require reviewers for signer/publication access.
- Store existing FIRMWARE_SIGNING_KEY_PEM, ANDROID_SIGNING_KEYSTORE_BASE64 and
  ANDROID_SIGNING_PASSWORD only in release-signing. Compare public fingerprints
  before use. Never upload a local generated development identity as a replacement.
- Store RELEASE_PROPOSAL_TOKEN separately from RELEASE_PUBLICATION_TOKEN. Give
  each only the repository permissions its workflow needs; untrusted validation
  never inherits them. The main/release SONAR_TOKEN belongs to protected analysis/publication; the
  separate repository PR analysis credential never grants publication access.
- Configure public Sonar project Ryther_vomar with the required analyzers and an
  explicit quality gate. Verify real language extraction and report completeness.
  A missing token or unsupported analyzer fails; it is not a successful scan.
- Set FIRMWARE_CANDIDATE_URL and FIRMWARE_CANDIDATE_SHA256 to the exact signed
  candidate. Set AUTO_PUBLISH_RELEASES=true only after a successful complete dry
  run; ENABLE_PAGES=true opts into Pages deployment.
- FIRMWARE_QUALIFICATION_JSON must be independently reviewed, with true physical
  observations bound to exact candidate bytes. Do not set it from CI results.
- Enable immutable releases where available, Actions-based Pages and public
  security reporting as appropriate. Review actual remote settings after applying
  them; tracked YAML does not enforce branch protection by itself.

No GitHub publication/settings have been performed by this source preparation.
The first distribution proposal must be reviewed after the new public baseline
is pushed; 0.0.0 is only a bootstrap manifest, not a published distribution.

The publication environment additionally requires `NATIVE_QUALIFICATION_JSON`
and `DEPENDENCY_REVIEW_JSON`, independently reviewed after all exact artifacts
exist. See the [evidence contracts](releasing.md#delivered-dependencies-and-native-qualification).
They are publication gates, separate from PR merging and firmware's thirteen
physical checks. The tracked inventory generator and audit jobs provide input;
they cannot approve physical checks or unscanned vendor advisories themselves.
