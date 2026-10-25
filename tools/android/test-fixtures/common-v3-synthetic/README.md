# Synthetic common schema3 fixture

This is parser/interoperability evidence only. It contains tiny synthetic images
and a synthetic loader, all signed using one ephemeral P256 fixture key. The
private key existed only in a temporary directory and was deleted after fixture
generation. No project private key, device UID, anchor, original backup or actual
firmware is included. Synthetic qualification booleans exercise the producer;
they are not hardware evidence, and this ZIP must never be installed.

Generated with `tools/android/tests/test_common_v3_package.py::release3` and
`tools/firmware/package_common_android_update_v3.py::create_common_v3_bundle`.
The first-install descriptor contains the one actual template code-family record;
the outer manifest additionally retains one explicit legacy update record.

- `one-common.zip`: 53,972 bytes, SHA256 `ed5fb1037dcdf54c1084e952418dae1d94c34124572fbb11ad6f5ed3ff3d7309`.
- `public.der`: 91 bytes, SHA256 `944d71c3bc2443208f896c878d91d1c6bd4fbeb0974236324fcb85d4b9569b38`.
