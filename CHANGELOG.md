# Changelog

## [1.0.0](https://github.com/Ryther/vomar/compare/v1.1.0...v1.0.0) (2026-10-29)


### Features

* align coordinated firmware and native client updates ([82e7d74](https://github.com/Ryther/vomar/commit/82e7d740f408272729f93426ac754b4ab439756d))
* **android:** add common updates, device registry and DK provisioning ([c1643f5](https://github.com/Ryther/vomar/commit/c1643f5ca931f177c5a02ffa898ea38165ddc1f9))
* **android:** apply owner UI notes and integrate first-install ACL preparation ([71d7ff0](https://github.com/Ryther/vomar/commit/71d7ff0e397ebf7bd8ba17ba4a39b7ca8cc8a294))
* **android:** refine production UI and ship app 1.0.3 ([28e5c07](https://github.com/Ryther/vomar/commit/28e5c074919bb949eb90e6ee19767d6f39821d3a))
* **android:** show project releases with experimental firmware ([#24](https://github.com/Ryther/vomar/issues/24)) ([dff2d70](https://github.com/Ryther/vomar/commit/dff2d7027c01e9c38a7ac12f7f276deff599d295))
* **clients:** add native device management and coordinated release discovery ([d3bea16](https://github.com/Ryther/vomar/commit/d3bea169f1c8741518cab1c79f8307fe4867edfc))
* **desktop:** add bounded BLE and DK installation transactions ([dd4045c](https://github.com/Ryther/vomar/commit/dd4045c3c73ffceba70be58a7c77a3522858c645))
* **desktop:** add signed package engine and durable private sessions ([c40235b](https://github.com/Ryther/vomar/commit/c40235b231e62ed8c0557eb2c9964ddb6760ddc2))
* **dev:** add public lean container and pinned assistant tooling ([eb2cbe4](https://github.com/Ryther/vomar/commit/eb2cbe4032b9090c096b60cc08742ede52d730b4))
* **firmware:** add common recovery, protected OTA and dimmer runtime ([ef1eec0](https://github.com/Ryther/vomar/commit/ef1eec0f24f71ba81e3727ae3adb61d859c890a7))
* **firmware:** integrate phase selection, Identify and release safeguards ([0aca5cb](https://github.com/Ryther/vomar/commit/0aca5cb3e1169a5e30e620e9539f6825628309b8))
* **release:** add exact-candidate automation and verified native distribution ([b9c3153](https://github.com/Ryther/vomar/commit/b9c3153012dee7a07439d4a2770bc39b580a3f32))
* **release:** define coordinated distribution and signer continuity ([bbf998a](https://github.com/Ryther/vomar/commit/bbf998abcb8078635fb2e587ba5a09d11174da25))
* **release:** deliver complete distributions with explicit firmware acceptance ([2dfa030](https://github.com/Ryther/vomar/commit/2dfa030530efb5fc096f62b0507aa19743451ecc))
* **research:** add reproducible exporters and optional evidence checks ([a727cbe](https://github.com/Ryther/vomar/commit/a727cbe62a7badf92a0d8eeeb1c5b8ecc01ba1ea))
* **tools:** add portable backup, provisioning and firmware qualification ([ef994ee](https://github.com/Ryther/vomar/commit/ef994ee6fb2b592aed3790104005b390d3d5f74e))
* tune Vimar defaults and migrate Android toolchain ([#15](https://github.com/Ryther/vomar/issues/15)) ([de7db74](https://github.com/Ryther/vomar/commit/de7db744e0b6288023aa1f8084dc4eff25ecbad4))
* **zigbee2mqtt:** add LED profiles, timers and fault diagnostics ([03abd9b](https://github.com/Ryther/vomar/commit/03abd9bc195dc8b7e1a452cd0b7ba29e4d28aebd))


### Bug Fixes

* **android:** invalidate runtime inventory when source identity changes ([527d3d9](https://github.com/Ryther/vomar/commit/527d3d910eae03f97adabb8d2524c49a882b4b9a))
* **android:** refresh saved Zigbee device firmware metadata ([ddee6e3](https://github.com/Ryther/vomar/commit/ddee6e3cb58c8c95bee576e51427e4b0d5818f7f))
* **build:** verify missing Android toolchain metadata ([460cb3c](https://github.com/Ryther/vomar/commit/460cb3cb1f71d99efbeca042e1126031fbd59959))
* **ci:** align shared infrastructure and user guides ([78e6ffd](https://github.com/Ryther/vomar/commit/78e6ffdc84f886c736dd7c8a6fe54d827dd8bd62))
* **ci:** align validation and development environment ([#11](https://github.com/Ryther/vomar/issues/11)) ([6f4bd75](https://github.com/Ryther/vomar/commit/6f4bd75cf973f3e8d8ba9717ff4dcf4f175c08bd))
* **ci:** repair post-validation assembly and Sonar workflows ([#18](https://github.com/Ryther/vomar/issues/18)) ([915ef34](https://github.com/Ryther/vomar/commit/915ef34e727b6187e18cb10b1f0214ab38d4e37b))
* **ci:** resolve Sonar report paths from the workspace ([#19](https://github.com/Ryther/vomar/issues/19)) ([0f54510](https://github.com/Ryther/vomar/commit/0f545106bb1d588ccd65fcd06fdb0a435428f9f9))
* **ci:** support reviewed exact Sonar false positives ([#21](https://github.com/Ryther/vomar/issues/21)) ([150b1ef](https://github.com/Ryther/vomar/commit/150b1efa8d3fd73a45c2604c2f124d1527adfd21))
* **desktop:** bound package acquisition before reading documents ([e026b2a](https://github.com/Ryther/vomar/commit/e026b2a61d6e7c7b029d4c67ee97f6839c87c8e8))
* **devcontainer:** include Docker and GitHub tooling with startup checks ([24b680d](https://github.com/Ryther/vomar/commit/24b680d5d6faf5fb74e43ac6e02708ba6551cff0))
* **firmware:** retain SDK failures across compatible recovery updates ([e1daedd](https://github.com/Ryther/vomar/commit/e1daedd9e360a44bfd24934fee2c2c7187416ffe))
* **release:** close review gaps in cancellation and distribution evidence ([f389585](https://github.com/Ryther/vomar/commit/f389585d6ecbd5574c339f6c2f5fea7445ea9b47))


### Miscellaneous Chores

* **main:** release 1.0.0 ([#23](https://github.com/Ryther/vomar/issues/23)) ([89258f2](https://github.com/Ryther/vomar/commit/89258f2938ac16f5970bc6e52051980646ce145a))

## [1.1.0](https://github.com/Ryther/vomar/compare/v1.0.0...v1.1.0) (2026-10-29)


### Features

* **firmware:** integrate phase selection, Identify and release safeguards ([0aca5cb](https://github.com/Ryther/vomar/commit/0aca5cb3e1169a5e30e620e9539f6825628309b8))


### Bug Fixes

* **firmware:** retain SDK failures across compatible recovery updates ([e1daedd](https://github.com/Ryther/vomar/commit/e1daedd9e360a44bfd24934fee2c2c7187416ffe))

## [1.0.0](https://github.com/Ryther/vomar/compare/v2.0.0...v1.0.0) (2026-10-28)


### Features

* **android:** show project releases with experimental firmware ([#24](https://github.com/Ryther/vomar/issues/24)) ([dff2d70](https://github.com/Ryther/vomar/commit/dff2d7027c01e9c38a7ac12f7f276deff599d295))

## 2.0.0 (2026-10-28)


### Features

* align coordinated firmware and native client updates ([82e7d74](https://github.com/Ryther/vomar/commit/82e7d740f408272729f93426ac754b4ab439756d))
* **android:** add common updates, device registry and DK provisioning ([c1643f5](https://github.com/Ryther/vomar/commit/c1643f5ca931f177c5a02ffa898ea38165ddc1f9))
* **android:** apply owner UI notes and integrate first-install ACL preparation ([71d7ff0](https://github.com/Ryther/vomar/commit/71d7ff0e397ebf7bd8ba17ba4a39b7ca8cc8a294))
* **android:** refine production UI and ship app 1.0.3 ([28e5c07](https://github.com/Ryther/vomar/commit/28e5c074919bb949eb90e6ee19767d6f39821d3a))
* **clients:** add native device management and coordinated release discovery ([d3bea16](https://github.com/Ryther/vomar/commit/d3bea169f1c8741518cab1c79f8307fe4867edfc))
* **desktop:** add bounded BLE and DK installation transactions ([dd4045c](https://github.com/Ryther/vomar/commit/dd4045c3c73ffceba70be58a7c77a3522858c645))
* **desktop:** add signed package engine and durable private sessions ([c40235b](https://github.com/Ryther/vomar/commit/c40235b231e62ed8c0557eb2c9964ddb6760ddc2))
* **dev:** add public lean container and pinned assistant tooling ([eb2cbe4](https://github.com/Ryther/vomar/commit/eb2cbe4032b9090c096b60cc08742ede52d730b4))
* **firmware:** add common recovery, protected OTA and dimmer runtime ([ef1eec0](https://github.com/Ryther/vomar/commit/ef1eec0f24f71ba81e3727ae3adb61d859c890a7))
* **release:** add exact-candidate automation and verified native distribution ([b9c3153](https://github.com/Ryther/vomar/commit/b9c3153012dee7a07439d4a2770bc39b580a3f32))
* **release:** define coordinated distribution and signer continuity ([bbf998a](https://github.com/Ryther/vomar/commit/bbf998abcb8078635fb2e587ba5a09d11174da25))
* **release:** deliver complete distributions with explicit firmware acceptance ([2dfa030](https://github.com/Ryther/vomar/commit/2dfa030530efb5fc096f62b0507aa19743451ecc))
* **research:** add reproducible exporters and optional evidence checks ([a727cbe](https://github.com/Ryther/vomar/commit/a727cbe62a7badf92a0d8eeeb1c5b8ecc01ba1ea))
* **tools:** add portable backup, provisioning and firmware qualification ([ef994ee](https://github.com/Ryther/vomar/commit/ef994ee6fb2b592aed3790104005b390d3d5f74e))
* tune Vimar defaults and migrate Android toolchain ([#15](https://github.com/Ryther/vomar/issues/15)) ([de7db74](https://github.com/Ryther/vomar/commit/de7db744e0b6288023aa1f8084dc4eff25ecbad4))
* **zigbee2mqtt:** add LED profiles, timers and fault diagnostics ([03abd9b](https://github.com/Ryther/vomar/commit/03abd9bc195dc8b7e1a452cd0b7ba29e4d28aebd))


### Bug Fixes

* **android:** invalidate runtime inventory when source identity changes ([527d3d9](https://github.com/Ryther/vomar/commit/527d3d910eae03f97adabb8d2524c49a882b4b9a))
* **android:** refresh saved Zigbee device firmware metadata ([ddee6e3](https://github.com/Ryther/vomar/commit/ddee6e3cb58c8c95bee576e51427e4b0d5818f7f))
* **build:** verify missing Android toolchain metadata ([460cb3c](https://github.com/Ryther/vomar/commit/460cb3cb1f71d99efbeca042e1126031fbd59959))
* **ci:** align shared infrastructure and user guides ([78e6ffd](https://github.com/Ryther/vomar/commit/78e6ffdc84f886c736dd7c8a6fe54d827dd8bd62))
* **ci:** align validation and development environment ([#11](https://github.com/Ryther/vomar/issues/11)) ([6f4bd75](https://github.com/Ryther/vomar/commit/6f4bd75cf973f3e8d8ba9717ff4dcf4f175c08bd))
* **ci:** repair post-validation assembly and Sonar workflows ([#18](https://github.com/Ryther/vomar/issues/18)) ([915ef34](https://github.com/Ryther/vomar/commit/915ef34e727b6187e18cb10b1f0214ab38d4e37b))
* **ci:** resolve Sonar report paths from the workspace ([#19](https://github.com/Ryther/vomar/issues/19)) ([0f54510](https://github.com/Ryther/vomar/commit/0f545106bb1d588ccd65fcd06fdb0a435428f9f9))
* **ci:** support reviewed exact Sonar false positives ([#21](https://github.com/Ryther/vomar/issues/21)) ([150b1ef](https://github.com/Ryther/vomar/commit/150b1efa8d3fd73a45c2604c2f124d1527adfd21))
* **desktop:** bound package acquisition before reading documents ([e026b2a](https://github.com/Ryther/vomar/commit/e026b2a61d6e7c7b029d4c67ee97f6839c87c8e8))
* **devcontainer:** include Docker and GitHub tooling with startup checks ([24b680d](https://github.com/Ryther/vomar/commit/24b680d5d6faf5fb74e43ac6e02708ba6551cff0))
* **release:** close review gaps in cancellation and distribution evidence ([f389585](https://github.com/Ryther/vomar/commit/f389585d6ecbd5574c339f6c2f5fea7445ea9b47))

## Changelog

No coordinated distribution has been published. Component firmware and Android
versions are independent of the initial distribution version 0.0.0.
