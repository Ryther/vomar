# Vomar brand artwork

The supplied concept 01 artwork is the source of truth: an open switch with an
amber V, a graphite frame, and an `opensource` ring in the banner wordmark.
Preserve the raster artwork, proportions, transparent negative space and colors.

`manifest.json` records the original sizes and SHA-256 hashes of all eleven
images. The original ZIP has SHA-256
`d8ed9acf7c9e1f19f7e79cb8f1327f8e9c7e2addc1ad91bdf236dea341090cf9`;
the ZIP itself is private workspace input and is not required for builds.

From the repository root:

```sh
python -m tools.release.branding --sync
python -m tools.release.branding --check
```

Synchronization copies original bytes into Android, desktop and documentation
resources. Check mode verifies every original and distributed copy without
writing. Both modes reject symlinked paths and a modified original. CI and
desktop packaging require a successful check.

Use the banner for the README and documentation home. Use the standalone symbol
for application and system icons. Small in-app marks sit on the existing ivory
surface (`#FAF8F3`) so the graphite frame remains visible in either theme.
Android uses the supplied 512 px symbol as an adaptive icon foreground with a
separate ivory background; it does not recolor the artwork. Windows uses the
original multi-resolution ICO. The macOS native build arranges the supplied
PNGs into an iconset and runs the system `iconutil`, without an extra image
conversion dependency. Generated ICNS files stay in the build output.
