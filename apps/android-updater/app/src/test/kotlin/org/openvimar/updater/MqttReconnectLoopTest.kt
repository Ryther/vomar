package org.openvimar.updater

import java.net.ConnectException
import javax.net.ssl.SSLException
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import org.eclipse.paho.client.mqttv3.MqttException
import org.junit.Assert.*
import org.junit.Test

/** Deterministic retry gates: no clock sleeps, broker, preferences or household data. */
class MqttReconnectLoopTest {
    @Test fun restorationConnectsImmediatelyThenLossCreatesAnotherSession()=runBlocking {
        val state=MutableStateFlow(NetworkBackendState())
        val connected=Channel<Int>(Channel.UNLIMITED);val waits=Channel<Long>(Channel.UNLIMITED)
        val release=Channel<Unit>();var attempts=0
        val loop=MqttReconnectLoop(this,state,{
            state.value=NetworkBackendState(connected=true);connected.send(++attempts)
        },{}, { ms->waits.send(ms);release.receive() })
        try { withTimeout(2000) {
            loop.start(connectImmediately=true)
            assertEquals(1,connected.receive())
            state.value=NetworkBackendState(connectionError=true)
            assertEquals(1000L,waits.receive())
            assertEquals(1,attempts)
            release.send(Unit)
            assertEquals(2,connected.receive())
        }} finally {loop.stop()}
    }

    @Test fun transientFailuresBackOffAndCapAtThirtySeconds()=runBlocking {
        val state=MutableStateFlow(NetworkBackendState(connectionError=true))
        val waits=Channel<Long>(Channel.UNLIMITED);val release=Channel<Unit>()
        var attempts=0
        val loop=MqttReconnectLoop(this,state,{attempts++;throw ConnectException("synthetic")},{},
            {ms->waits.send(ms);release.receive()})
        try {withTimeout(2000) {
            loop.start(initialFailure=ConnectException())
            listOf(1000L,2000L,4000L,8000L,16000L,30000L,30000L).forEachIndexed { i,expected->
                assertEquals(expected,waits.receive());assertEquals(i,attempts);release.send(Unit)
            }
        }} finally {loop.stop()}
    }

    @Test fun authenticationTlsAndUnknownFailuresDoNotRetry()=runBlocking {
        for(error in listOf(MqttException(MqttException.REASON_CODE_FAILED_AUTHENTICATION.toInt()),
            MqttException(MqttException.REASON_CODE_NOT_AUTHORIZED.toInt()),SSLException("fixture"),IllegalStateException("invalid settings"))) {
            var retries=0
            val loop=MqttReconnectLoop(this,MutableStateFlow(NetworkBackendState(connectionError=true)),{retries++},{}, {retries++})
            loop.start(initialFailure=error);yield();loop.stop()
            assertEquals(0,retries)
        }
    }

    @Test fun explicitStopCancelsPendingRetryAndRestartCannotReconnectOldSelection()=runBlocking {
        val waits=Channel<Long>(Channel.UNLIMITED);val release=Channel<Unit>()
        val connected=Channel<String>(Channel.UNLIMITED)
        val state=MutableStateFlow(NetworkBackendState(connectionError=true));var profile="old"
        val loop=MqttReconnectLoop(this,state,{connected.send(profile);state.value=NetworkBackendState(connected=true)},{},
            {ms->waits.send(ms);release.receive()})
        try {withTimeout(2000) {
            loop.start(initialFailure=ConnectException());waits.receive()
            loop.stop();yield()
            assertTrue(connected.tryReceive().isFailure)
            profile="new";loop.start(connectImmediately=true)
            assertEquals("new",connected.receive());assertTrue(connected.tryReceive().isFailure)
        }} finally {loop.stop()}
    }

    @Test fun stoppingAnInFlightAttemptCompletesItsCleanupWithoutRetry()=runBlocking {
        val entered=CompletableDeferred<Unit>();val cleaned=CompletableDeferred<Unit>();var waits=0
        val loop=MqttReconnectLoop(this,MutableStateFlow(NetworkBackendState()),{
            try {entered.complete(Unit);awaitCancellation()}
            finally {withContext(NonCancellable){yield();cleaned.complete(Unit)}}
        },{}, {waits++})
        try {withTimeout(2000) {
            loop.start(connectImmediately=true);entered.await();loop.stop();cleaned.await()
            assertEquals(0,waits)
        }} finally {loop.stop()}
    }

    @Test fun aPermanentFailureDuringRestorationStopsAfterOneAttempt()=runBlocking {
        var attempts=0;var waits=0
        val loop=MqttReconnectLoop(this,MutableStateFlow(NetworkBackendState()),{
            attempts++;throw MqttException(MqttException.REASON_CODE_FAILED_AUTHENTICATION.toInt())
        },{}, {waits++})
        loop.start(connectImmediately=true);yield();loop.stop()
        assertEquals(1,attempts);assertEquals(0,waits)
    }
}
