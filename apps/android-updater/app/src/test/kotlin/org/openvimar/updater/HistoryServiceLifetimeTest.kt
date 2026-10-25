package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test

class HistoryServiceLifetimeTest {
 @Test fun acceptedOwnerRetainsOnlyItsStartedServiceIdUntilIdle() {
  val lifetime=HistoryServiceLifetime();assertTrue(lifetime.keepAlive(7,true))
  assertEquals(7,lifetime.releaseOnIdle());assertNull(lifetime.releaseOnIdle())
 }
 @Test fun lateKeepAliveWithNoOwnerCannotCreateAnIdleForegroundLease() {
  val lifetime=HistoryServiceLifetime();assertFalse(lifetime.keepAlive(9,false));assertNull(lifetime.releaseOnIdle())
 }
 @Test fun replacingStartedOwnerReleasesLatestIdAndCannotStopALaterUnrelatedStart() {
  val lifetime=HistoryServiceLifetime();assertTrue(lifetime.keepAlive(4,true));assertTrue(lifetime.keepAlive(5,true))
  // Service uses stopSelf(5), preserving a later framework startId instead of stopSelf().
  assertEquals(5,lifetime.releaseOnIdle());assertFalse(lifetime.keepAlive(6,false));assertNull(lifetime.releaseOnIdle())
 }
}
