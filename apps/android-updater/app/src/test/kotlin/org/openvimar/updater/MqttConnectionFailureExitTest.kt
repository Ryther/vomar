package org.openvimar.updater

import java.io.IOException
import java.net.UnknownHostException
import kotlinx.coroutines.*
import org.eclipse.paho.client.mqttv3.MqttException
import org.eclipse.paho.client.mqttv3.MqttSecurityException
import org.junit.Assert.*
import org.junit.Test

class MqttConnectionFailureExitTest {
    @Test fun cancellationFinishesSuspendingCleanupAndPublishesStoppedWithoutClassifyingItsCause()=runBlocking {
        var state=NetworkBackendState(status="Connecting")
        var cleanupFinished=false
        var cleanupCalls=0
        var original:CancellationException?=null
        var propagated:Exception?=null
        val entered=CompletableDeferred<Unit>()
        val worker=launch {
            try { entered.complete(Unit);awaitCancellation() }
            catch(e:CancellationException) {
                original=e
                try {
                    finishFailedMqttConnection(e,{
                        cleanupCalls++
                        yield() // Cancellable suspension: this must still complete after cancellation.
                        cleanupFinished=true
                    },{ state=it })
                } catch(f:Exception) { propagated=f;throw f }
            }
        }
        entered.await()
        worker.cancel(CancellationException("fixture-password user stopped").apply {
            initCause(MqttSecurityException(MqttException.REASON_CODE_FAILED_AUTHENTICATION.toInt()))
        })
        worker.join()
        assertTrue(cleanupFinished)
        assertEquals(1,cleanupCalls)
        assertFalse(state.connected)
        assertEquals("Connection stopped.",state.status)
        assertSame(original,propagated)
        assertFalse(state.status.contains("fixture-password"))
    }

    @Test fun cleanupFailurePreservesOriginalCauseAndPublishesItsSafeConnectionError()=runBlocking {
        val original=IOException("fixture-password",UnknownHostException("private-broker.example"))
        val cleanup=IOException("fixture-secret cleanup")
        var state=NetworkBackendState(status="Connecting")
        var propagated:Exception?=null
        try { finishFailedMqttConnection(original,{ throw cleanup },{ state=it }) }
        catch(e:Exception) { propagated=e }
        assertSame(original,propagated)
        assertTrue(original.suppressed.contains(cleanup))
        assertFalse(state.connected)
        assertTrue(state.status.contains("hostname",true))
        listOf("fixture-password","fixture-secret","private-broker.example").forEach { assertFalse(state.status.contains(it)) }
    }

    @Test fun ordinaryFailureCleansUpOnceAndKeepsTheActionableDnsMessage()=runBlocking {
        val original=IOException("fixture-password",UnknownHostException("private-broker.example"))
        var cleanupCalls=0
        var state=NetworkBackendState(status="Connecting")
        var propagated:Exception?=null
        try { finishFailedMqttConnection(original,{ yield();cleanupCalls++ },{ state=it }) }
        catch(e:Exception) { propagated=e }
        assertSame(original,propagated)
        assertEquals(1,cleanupCalls)
        assertFalse(state.connected)
        assertTrue(state.status.contains("hostname",true))
    }

    @Test fun failedCleanupCannotReplaceCancellationOrItsStoppedState()=runBlocking {
        val original=CancellationException("fixture-password user stopped")
        val cleanup=IOException("fixture-secret cleanup")
        var state=NetworkBackendState(status="Connecting")
        var propagated:Exception?=null
        try { finishFailedMqttConnection(original,{ throw cleanup },{ state=it }) }
        catch(e:Exception) { propagated=e }
        assertSame(original,propagated)
        assertTrue(original.suppressed.contains(cleanup))
        assertFalse(state.connected)
        assertEquals("Connection stopped.",state.status)
    }
}
