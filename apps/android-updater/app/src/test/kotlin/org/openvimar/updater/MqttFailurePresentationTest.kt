package org.openvimar.updater

import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.security.cert.CertificateException
import java.util.concurrent.TimeoutException
import javax.net.ssl.SSLHandshakeException
import javax.net.ssl.SSLPeerUnverifiedException
import org.eclipse.paho.client.mqttv3.MqttException
import org.eclipse.paho.client.mqttv3.MqttSecurityException
import org.junit.Assert.*
import org.junit.Test

class MqttFailurePresentationTest {
    @Test fun droppedTransportDuringSubscriptionIsTransient() {
        for(error in listOf(NetworkLostException(),
            MqttException(MqttException.REASON_CODE_CONNECTION_LOST.toInt()),
            MqttException(MqttException.REASON_CODE_CLIENT_NOT_CONNECTED.toInt()))) {
            assertEquals(MqttFailureKind.UNREACHABLE,presentMqttFailure(error).kind)
        }
    }
    private val sensitive="private-broker.example fixture-user fixture-password"

    @Test fun pahoAndIoWrappersPreserveDnsPortAndTimeoutCauses() {
        listOf(
            UnknownHostException(sensitive) to MqttFailureKind.DNS,
            ConnectException(sensitive) to MqttFailureKind.UNREACHABLE,
            NoRouteToHostException(sensitive) to MqttFailureKind.UNREACHABLE,
            SocketTimeoutException(sensitive) to MqttFailureKind.TIMEOUT,
            TimeoutException(sensitive) to MqttFailureKind.TIMEOUT
        ).forEach { (cause,kind) ->
            val wrapper=IOException("MQTT operation failed $sensitive",MqttException(cause))
            assertEquals(kind,presentMqttFailure(wrapper).kind)
        }
    }

    @Test fun certificateAndHandshakeFailuresProvideTlsGuidance() {
        listOf(SSLHandshakeException(sensitive),SSLPeerUnverifiedException(sensitive),CertificateException(sensitive)).forEach {
            val presentation=presentMqttFailure(IOException(sensitive,MqttException(it)))
            assertEquals(MqttFailureKind.TLS,presentation.kind)
            assertTrue(presentation.nextAction.contains("certificate",true))
        }
    }

    @Test fun authenticationAndAuthorizationReasonCodesStayDistinct() {
        val authentication=presentMqttFailure(IOException(sensitive,MqttSecurityException(MqttException.REASON_CODE_FAILED_AUTHENTICATION.toInt())))
        val authorization=presentMqttFailure(IOException(sensitive,MqttSecurityException(MqttException.REASON_CODE_NOT_AUTHORIZED.toInt())))
        assertEquals(MqttFailureKind.AUTHENTICATION,authentication.kind)
        assertTrue(authentication.nextAction.contains("credentials",true))
        assertEquals(MqttFailureKind.NOT_AUTHORIZED,authorization.kind)
        assertTrue(authorization.nextAction.contains("permissions",true))
    }

    @Test fun pahoTimeoutAndUnavailableServerCodesHaveActionableFallbacks() {
        listOf(
            MqttException.REASON_CODE_CLIENT_TIMEOUT to MqttFailureKind.TIMEOUT,
            MqttException.REASON_CODE_WRITE_TIMEOUT to MqttFailureKind.TIMEOUT,
            MqttException.REASON_CODE_BROKER_UNAVAILABLE to MqttFailureKind.UNREACHABLE,
            MqttException.REASON_CODE_SERVER_CONNECT_ERROR to MqttFailureKind.UNREACHABLE,
            MqttException.REASON_CODE_SSL_CONFIG_ERROR to MqttFailureKind.TLS
        ).forEach { (code,expected) ->
            assertEquals(expected,presentMqttFailure(IOException(sensitive,MqttException(code.toInt()))).kind)
        }
    }

    @Test fun genericServerConnectCodeDoesNotHideNestedDnsFailure() {
        val failure=MqttException(MqttException.REASON_CODE_SERVER_CONNECT_ERROR.toInt(),UnknownHostException(sensitive))
        assertEquals(MqttFailureKind.DNS,presentMqttFailure(failure).kind)
    }

    @Test fun exceptionTextNeverDeterminesTheCategoryOrAppearsInPresentation() {
        listOf(
            IOException("TLS password authentication timeout $sensitive"),
            UnknownHostException(sensitive),ConnectException(sensitive),SocketTimeoutException(sensitive),
            SSLHandshakeException(sensitive),MqttException(IOException(sensitive)),
            IOException(sensitive,MqttSecurityException(MqttException.REASON_CODE_FAILED_AUTHENTICATION.toInt())),
            IOException(sensitive,MqttSecurityException(MqttException.REASON_CODE_NOT_AUTHORIZED.toInt()))
        ).forEach { error ->
            val presentation=presentMqttFailure(error)
            val shown="${presentation.message} ${presentation.nextAction} ${presentation.kind}"
            sensitive.split(' ').forEach { assertFalse(shown.contains(it)) }
            assertTrue(presentation.message.isNotBlank())
            assertTrue(presentation.nextAction.isNotBlank())
        }
        assertEquals(MqttFailureKind.UNKNOWN,presentMqttFailure(IOException("authentication timeout")).kind)
    }

    @Test(timeout=1000) fun cyclicAndExcessivelyDeepCausesTerminate() {
        val first=IOException(sensitive);val second=IOException(sensitive)
        first.initCause(second);second.initCause(first)
        assertEquals(MqttFailureKind.UNKNOWN,presentMqttFailure(first).kind)
        var deep:Throwable=UnknownHostException(sensitive)
        repeat(64) { deep=IOException(sensitive,deep) }
        assertEquals(MqttFailureKind.UNKNOWN,presentMqttFailure(deep).kind)
    }
}
