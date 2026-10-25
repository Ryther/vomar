package org.openvimar.updater

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.openvimar.updater.core.*

class CommonIdentityControllerTest {
    @Test fun readOnlyDiscoveryPublishesTypedIdentityWithoutAReleaseOrMutationGrant()=runBlocking {
        val h=Harness();h.inspector={_,check->check();RuntimeIdentity(2,"VIMAR30805",2,listOf("11223344","55667788"),"",LoaderContract(LoaderContract.COMMON,"a".repeat(64)),"b".repeat(64))}
        assertTrue(h.controller.inspectIdentity("AA:BB:CC:DD:EE:FF"));h.controller.awaitIdle()
        assertEquals(2,h.controller.reportedIdentity.value!!.identity.protocol)
        assertNull(h.controller.presentation.value.packageSummary);h.scope.cancel()
    }
    private class Harness {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
        var permitted=true
        var inspector:suspend(String,()->Unit)->RuntimeIdentity={_,check->check();RuntimeIdentity(1,"VIMAR30805",2,listOf("11223344","55667788"),"a".repeat(64))}
        val controller=SessionController(scope,object:SessionStore {
            override suspend fun load(bundleDigest:String,address:String):Checkpoint?=null
            override suspend fun save(checkpoint:Checkpoint)=error("Identity inspection must not save checkpoints")
        },{null},{null},{_,_,_->error("No import requested")},{error("Update transport must not be created")},
            {_,_,_->error("No update report expected")},{byteArrayOf()},{permitted},identityInspector={address,check->inspector(address,check)})
    }
    @Test fun identityInspectionWorksWithoutAReleaseOrRegistryAndRecordsItsAddress()=runBlocking {
        val h=Harness()
        assertTrue(h.controller.inspectIdentity("AA:BB:CC:DD:EE:FF"));h.controller.awaitIdle()
        val observed=h.controller.reportedIdentity.value!!
        assertEquals("AA:BB:CC:DD:EE:FF",observed.address)
        assertEquals(listOf("11223344","55667788"),observed.identity.uid)
        assertNull(h.controller.presentation.value.packageSummary)
        h.scope.cancel()
    }
    @Test fun stoppedInspectionCannotPublishLateIdentityOrRaceAnotherCommand()=runBlocking {
        val h=Harness();val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
        h.inspector={_,check->entered.complete(Unit);withContext(NonCancellable){release.await()};check();RuntimeIdentity(1,"VIMAR30805",2,listOf("11223344","55667788"),"a".repeat(64))}
        h.controller.inspectIdentity("AA:BB:CC:DD:EE:FF");entered.await()
        assertFalse(h.controller.inspectIdentity("AA:BB:CC:DD:EE:00"))
        h.controller.stop();release.complete(Unit);h.controller.awaitIdle()
        assertNull(h.controller.reportedIdentity.value)
        h.scope.cancel()
    }
    @Test fun permissionRevocationOrMalformedIdentityLeavesNoStaleObservation()=runBlocking {
        val h=Harness();h.controller.inspectIdentity("AA:BB:CC:DD:EE:FF");h.controller.awaitIdle()
        assertNotNull(h.controller.reportedIdentity.value)
        h.permitted=false;h.controller.inspectIdentity("AA:BB:CC:DD:EE:FF");h.controller.awaitIdle()
        assertNull(h.controller.reportedIdentity.value)
        h.permitted=true;h.inspector={_,_->RuntimeIdentity(1,"VIMAR30805",2,listOf("1","2"),"a".repeat(64))}
        h.controller.inspectIdentity("AA:BB:CC:DD:EE:FF");h.controller.awaitIdle()
        assertNull(h.controller.reportedIdentity.value)
        h.scope.cancel()
    }
    @Test fun fleetAndManualCommandsShareTheSameBluetoothOwnerAndDrainCancellation()=runBlocking {
        val h=Harness();val entered=CompletableDeferred<Unit>();val closed=CompletableDeferred<Unit>()
        val task=async {h.controller.executeFleet {check->try{check();entered.complete(Unit);awaitCancellation()}finally{closed.complete(Unit)}}}
        entered.await();assertFalse(h.controller.inspectIdentity("AA:BB:CC:DD:EE:FF"))
        task.cancelAndJoin();closed.await();h.controller.awaitIdle()
        assertFalse(h.controller.busy.value);assertTrue(h.controller.inspectIdentity("AA:BB:CC:DD:EE:FF"));h.controller.awaitIdle()
        h.scope.cancel()
    }
    @Test fun fleetCancellationCanReturnDurableUncertainEvidenceAfterRadioTeardown()=runBlocking {
        val h=Harness();val entered=CompletableDeferred<Unit>();var outcome:String?=null
        val task=launch{outcome=h.controller.executeFleet {_->
            entered.complete(Unit);try{awaitCancellation()}catch(_:CancellationException){"uncertain reset"}
        }}
        entered.await();task.cancelAndJoin();assertEquals("uncertain reset",outcome);assertFalse(h.controller.busy.value)
        h.scope.cancel()
    }
    @Test fun detachingLegacyUpdateHostDoesNotCancelTheSeparatelyHostedFleetLease()=runBlocking {
        val h=Harness();val entered=CompletableDeferred<Unit>();var closed=false
        val task=launch{h.controller.executeFleet{_->try{entered.complete(Unit);awaitCancellation()}finally{closed=true}}}
        entered.await();h.controller.detachUpdateHost();assertTrue(h.controller.busy.value);assertFalse(closed)
        task.cancelAndJoin();assertTrue(closed);assertFalse(h.controller.busy.value);h.scope.cancel()
    }
}
