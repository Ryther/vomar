package org.openvimar.updater

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first

/** Reconnect subscriptions through a fresh session; commands never enter this loop. */
internal class MqttReconnectLoop(
    private val scope:CoroutineScope,
    private val state:StateFlow<NetworkBackendState>,
    private val attempt:suspend ()->Unit,
    private val waiting:(Long)->Unit,
    private val pause:suspend (Long)->Unit={delay(it)}
) {
    private var job:Job?=null
    fun start(connectImmediately:Boolean=false,initialFailure:Exception?=null) {
        stop()
        job=scope.launch {
            var immediate=connectImmediately
            var failure=initialFailure
            var delayMs=1000L
            while(isActive) {
                if(!immediate) {
                    if(failure==null)state.first { !it.connected && it.connectionError }
                    if(failure!=null && presentMqttFailure(failure).kind !in setOf(
                            MqttFailureKind.DNS,MqttFailureKind.UNREACHABLE,MqttFailureKind.TIMEOUT))return@launch
                    waiting(delayMs)
                    pause(delayMs)
                    delayMs=minOf(delayMs*2,30000L)
                }
                immediate=false
                try {
                    ensureActive()
                    attempt()
                    failure=null
                    delayMs=1000L
                } catch(cancelled:CancellationException) { throw cancelled }
                catch(error:Exception) { failure=error }
            }
        }
    }
    fun stop() { job?.cancel();job=null }
    suspend fun stopAndJoin() {
        val previous=job;job=null
        previous?.cancelAndJoin()
    }
}
