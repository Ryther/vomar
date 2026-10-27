package org.openvimar.updater

import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.security.cert.CertificateException
import java.security.cert.CertPathValidatorException
import java.util.Collections
import java.util.IdentityHashMap
import java.util.concurrent.TimeoutException
import javax.net.ssl.SSLException
import org.eclipse.paho.client.mqttv3.MqttException

internal enum class MqttFailureKind { DNS, UNREACHABLE, TIMEOUT, TLS, AUTHENTICATION, NOT_AUTHORIZED, UNKNOWN }

internal data class MqttFailurePresentation(val kind:MqttFailureKind,val message:String,val nextAction:String)

/** Bounded, cycle-safe cause inspection. Exception messages and broker input are never displayed. */
internal fun presentMqttFailure(error:Throwable):MqttFailurePresentation {
    val seen=Collections.newSetFromMap(IdentityHashMap<Throwable,Boolean>())
    var current:Throwable?=error
    var fallback=MqttFailureKind.UNKNOWN
    repeat(16) {
        val cause=current ?: return failurePresentation(fallback)
        if(!seen.add(cause))return failurePresentation(fallback)
        val kind=when(cause) {
            is NetworkLostException -> MqttFailureKind.UNREACHABLE
            is UnknownHostException -> MqttFailureKind.DNS
            is SocketTimeoutException,is TimeoutException -> MqttFailureKind.TIMEOUT
            is SSLException,is CertificateException,is CertPathValidatorException -> MqttFailureKind.TLS
            is ConnectException,is NoRouteToHostException -> MqttFailureKind.UNREACHABLE
            is MqttException -> when(cause.reasonCode) {
                MqttException.REASON_CODE_FAILED_AUTHENTICATION.toInt() -> MqttFailureKind.AUTHENTICATION
                MqttException.REASON_CODE_NOT_AUTHORIZED.toInt() -> MqttFailureKind.NOT_AUTHORIZED
                MqttException.REASON_CODE_CLIENT_TIMEOUT.toInt(),MqttException.REASON_CODE_WRITE_TIMEOUT.toInt() -> MqttFailureKind.TIMEOUT
                MqttException.REASON_CODE_SSL_CONFIG_ERROR.toInt(),MqttException.REASON_CODE_SOCKET_FACTORY_MISMATCH.toInt() -> MqttFailureKind.TLS
                MqttException.REASON_CODE_BROKER_UNAVAILABLE.toInt(),MqttException.REASON_CODE_SERVER_CONNECT_ERROR.toInt() -> {
                    // These generic Paho codes can wrap a more useful DNS or TLS cause.
                    fallback=MqttFailureKind.UNREACHABLE
                    null
                }
                MqttException.REASON_CODE_CONNECTION_LOST.toInt(),MqttException.REASON_CODE_CLIENT_NOT_CONNECTED.toInt() -> {
                    fallback=MqttFailureKind.UNREACHABLE
                    null
                }
                else -> null
            }
            else -> null
        }
        if(kind!=null)return failurePresentation(kind)
        current=cause.cause
    }
    return failurePresentation(fallback)
}

private fun failurePresentation(kind:MqttFailureKind):MqttFailurePresentation = when(kind) {
    MqttFailureKind.DNS -> MqttFailurePresentation(kind,"Broker address could not be found.","Check the broker hostname and your network or VPN.")
    MqttFailureKind.UNREACHABLE -> MqttFailurePresentation(kind,"Could not reach the broker.","Check the broker port and that the broker is running.")
    MqttFailureKind.TIMEOUT -> MqttFailurePresentation(kind,"The broker connection timed out.","Check your network connection and whether the broker is responding.")
    MqttFailureKind.TLS -> MqttFailurePresentation(kind,"The secure connection could not be established.","Check the broker certificate and the phone's date and time.")
    MqttFailureKind.AUTHENTICATION -> MqttFailurePresentation(kind,"The broker rejected the sign-in.","Check the saved credentials in network settings.")
    MqttFailureKind.NOT_AUTHORIZED -> MqttFailurePresentation(kind,"The broker denied access.","Ask the broker administrator to check this account's permissions.")
    MqttFailureKind.UNKNOWN -> MqttFailurePresentation(kind,"Could not connect to the broker.","Check the broker settings and saved credentials before trying again.")
}
