# Development signing key

`dev-public.pem` belongs only to this research platform. The matching
`dev-private.pem` is deliberately ignored by Git and must never be reused for a
production trust root.

Generate or rotate the local pair with:

```sh
openssl ecparam -name prime256v1 -genkey -noout -out firmware/keys/dev-private.pem
openssl ec -in firmware/keys/dev-private.pem -pubout -out firmware/keys/dev-public.pem
```

Rotating the key invalidates images signed with the previous key. No key rotation,
bootloader update, or programming is authorized on physical hardware by this file.
