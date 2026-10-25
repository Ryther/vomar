# GitHub setup

Complete local review before pushing. No tool here changes repository visibility,
branch settings, remote secrets, tags or published releases automatically.

- Protect main, require review and these stable checks: Conventional Commits,
  Workflow lint, Secrets, Firmware required, Android required, Desktop required,
  Contracts required, Documentation required, UX evidence gate, Sonar required
  and Dependencies required. Also require the language-specific CodeQL lanes.
- Use separate protected environments: release-proposal, release-signing,
  release-publication and sonar-analysis. Restrict them to the protected default
  branch/workflow and require reviewers for signer/publication access.
- Store existing FIRMWARE_SIGNING_KEY_PEM, ANDROID_SIGNING_KEYSTORE_BASE64 and
  ANDROID_SIGNING_PASSWORD only in release-signing. Compare public fingerprints
  before use. Never upload a local generated development identity as a replacement.
- Store RELEASE_PROPOSAL_TOKEN separately from RELEASE_PUBLICATION_TOKEN. Give
  each only the repository permissions its workflow needs; untrusted validation
  never inherits them. SONAR_TOKEN belongs only to protected analysis/publication.
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
