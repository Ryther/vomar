package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test

class FleetPolicyTest {
    private val pkg = PackageSummary("Desk", "0.5.8", "AA:BB:CC:DD:EE:FF", listOf("123", "456"), "digest", "target", "0.7.3")

    @Test fun anUnselectedPackageIsAnUncheckedComparisonRatherThanADeviceError() {
        val record=DeviceRecord.from(pkg).copy(installedVersion="1.1.6",firmwareKind=FirmwareKind.CUSTOM,
            observedAt=123,observationSource=ZigbeeDeviceMetadata.STATE)
        val status=FleetPolicy.status(record,SessionPresentation())
        assertEquals("Update not checked",status.label)
        assertEquals(DeviceStatusTone.NEUTRAL,status.tone)
        assertEquals(Eligibility.BLOCKED,status.eligibility)
        assertEquals(DeviceStatusTone.NEUTRAL,FleetPolicy.status(record,null as FleetReleaseRef?).tone)
    }
    @Test fun experimentalCatalogMetadataChangesPresentationWithoutGrantingUpdateAdmission() {
        val record=DeviceRecord.from(pkg).copy(installedVersion="1.1.6",firmwareKind=FirmwareKind.CUSTOM,
            observedAt=123,observationSource=ZigbeeDeviceMetadata.STATE)
        val status=FleetPolicy.status(record,SessionPresentation(),experimentalVersion="1.1.6")
        assertEquals("Experimental firmware",status.label)
        assertEquals(DeviceStatusTone.AVAILABLE,status.tone)
        assertEquals(Eligibility.BLOCKED,status.eligibility)
        assertEquals("Update not checked",FleetPolicy.status(record,SessionPresentation(),"1.1.5").label)
        assertEquals("Update not checked",FleetPolicy.status(record.copy(firmwareKind=FirmwareKind.UNKNOWN),SessionPresentation(),"1.1.6").label)
        assertEquals("Update not checked",FleetPolicy.status(record.copy(observedAt=null),SessionPresentation(),"1.1.6").label)
        assertEquals(DeviceStatusTone.ERROR,FleetPolicy.status(record.copy(uid=listOf("different")),SessionPresentation(loaded=true,packageSummary=pkg),"1.1.6").tone)
    }
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
    @Test fun zigbeeImportClassifiesOnlyStockAndVomarProjectDefinitions() {
        assertEquals(FirmwareKind.STOCK,FleetPolicy.zigbeeFirmwareKind("Vimar", "30805"))
        for(vendor in listOf("Vomar","vOmAr"))
            assertEquals(FirmwareKind.CUSTOM,FleetPolicy.zigbeeFirmwareKind(vendor, "30805-custom"))
        for((vendor,model) in listOf("OpenVimar" to "30805-custom","oPeNvImAr" to "30805-custom","Other vendor" to "30805-custom","Vomar" to "30805","OpenVimar" to "30805","Vimar" to "30805-custom","Vomar" to "30805-CUSTOM"))
            assertNull("$vendor / $model",FleetPolicy.zigbeeFirmwareKind(vendor,model))
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
