package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test

class FleetPolicyTest {
    private val pkg = PackageSummary("Desk", "0.5.8", "AA:BB:CC:DD:EE:FF", listOf("123", "456"), "digest", "target", "0.7.3")

    @Test fun aSavedNameOrAddressNeverAuthorizesAnUpdate() {
        val record = DeviceRecord("manual", "Desk", "Office")
        assertEquals(Eligibility.BLOCKED, FleetPolicy.status(record, SessionPresentation(loaded=true, packageSummary=pkg)).eligibility)
        assertFalse(FleetPolicy.matches(record, pkg))
    }
    @Test fun eligibilityNeedsLiveImageEvidenceAndNeverGuessesInstalledVersion() {
        val record = DeviceRecord.from(pkg)
        val selected = SessionPresentation(loaded=true, packageSummary=pkg)
        assertEquals(Eligibility.BLOCKED, FleetPolicy.status(record, selected).eligibility)
        assertEquals(Eligibility.UPDATE, FleetPolicy.status(record, selected.copy(bluetoothVerified=true, observedMainHash="source")).eligibility)
        assertEquals(Eligibility.CURRENT, FleetPolicy.status(record, selected.copy(bluetoothVerified=true, observedMainHash="target")).eligibility)
    }
    @Test fun aDifferentSignedPackageCannotInheritVerifiedStatus() {
        val record = DeviceRecord.from(pkg)
        val other = pkg.copy(uid=listOf("789"))
        assertEquals(Eligibility.BLOCKED, FleetPolicy.status(record, SessionPresentation(loaded=true,packageSummary=other,imagesVerified=true)).eligibility)
    }
    @Test fun zigbeeImportRecognisesTheStockAndActualProjectConverterDefinitions() {
        assertTrue(FleetPolicy.recognisesZigbee("Vimar", "30805"))
        assertTrue(FleetPolicy.recognisesZigbee("OpenVimar", "30805-custom"))
        assertFalse(FleetPolicy.recognisesZigbee("Other vendor", "30805"))
        assertFalse(FleetPolicy.recognisesZigbee("Vimar", "other"))
    }
    @Test fun publicSourceAcceptsOnlyAnUnambiguousGitHubRepository() {
        assertEquals("Ryther/vomar", ReleaseSource.parse("https://github.com/Ryther/vomar/"))
        assertEquals("owner/repo", ReleaseSource.parse("owner/repo"))
        listOf("http://github.com/a/b", "https://github.com.evil/a/b", "https://user:secret@github.com/a/b", "https://github.com/a/b/releases", "a/../b", "").forEach {
            assertNull(it, ReleaseSource.parse(it))
        }
    }
    @Test fun observedVersionAndRealRouteAreRequiredAndStockUnknownCurrentNewerStayHonest() {
        val release=FleetReleaseRef("a".repeat(64),"0.8.0","b".repeat(64),"/cache")
        val record=DeviceRecord("id","Desk",address="AA:BB:CC:DD:EE:FF",uid=listOf("11111111","22222222"),
            installedVersion="0.5.7.9",firmwareKind=FirmwareKind.CUSTOM,observedAt=123,observationSource="SMP image report")
        assertEquals(Eligibility.UPDATE,FleetPolicy.status(record,release).eligibility)
        assertEquals(Eligibility.CURRENT,FleetPolicy.status(record.copy(installedVersion="0.8.0"),release).eligibility)
        assertEquals(Eligibility.BLOCKED,FleetPolicy.status(record.copy(installedVersion="0.9.0"),release).eligibility)
        assertEquals("Stock firmware",FleetPolicy.status(record.copy(firmwareKind=FirmwareKind.STOCK),release).label)
        assertEquals("Check version",FleetPolicy.status(record.copy(observedAt=null),release).label)
        assertEquals("Check version",FleetPolicy.status(record.copy(installedVersion="unknown"),release).label)
    }
    @Test fun genericOtaSupportCannotAuthorizeProfileTwoNetworkRouteOrLegacyBleGuess() {
        val ota=ZigbeeOtaReference(0xfff1,0x3085,8,"c".repeat(64),123,"VIMAR30805",2,"https://example.org/main.ota")
        val release=FleetReleaseRef("a".repeat(64),"0.8.0","b".repeat(64),"/cache",zigbeeOta=ota,targetRecoveryHash="d".repeat(64))
        val record=DeviceRecord("id","Desk",networkId="net",ieee="0x123",capabilities=setOf("zigbee_ota"))
        assertNull(FleetPolicy.route(record,release))
        assertNull(FleetPolicy.route(record.copy(capabilities=record.capabilities+"zigbee_ota_profile2"),release))
        assertEquals(FleetRoute.ZIGBEE,FleetPolicy.route(record.copy(capabilities=record.capabilities+setOf("zigbee_ota_profile2","recovery_sha256:${"d".repeat(64)}")),release))
        assertNull(FleetPolicy.route(record.copy(capabilities=record.capabilities+"zigbee_ota_profile2"),release.copy(zigbeeOta=ota.copy(source=""))))
    }
}
