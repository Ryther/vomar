package org.openvimar.updater

import android.content.pm.ApplicationInfo
import android.security.NetworkSecurityPolicy
import android.test.AndroidTestCase
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketTimeoutException
import java.security.MessageDigest
import java.util.Base64
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.flow.first

/** Real Paho sockets against an in-process loopback fixture; no saved profiles or household services. */
class MqttCleartextPolicyTest:AndroidTestCase() {
    fun testInstalledAppAndProcessDenyCleartextByDefault() {
        assertCleartextDefaultDenied()
    }

    fun testExplicitLocalConsentAllowsRealTcpMqttWithoutRelaxingTheAppDefault()=exercise(false)

    fun testExplicitLocalConsentAllowsRealWebSocketMqttWithoutRelaxingTheAppDefault()=exercise(true)

    private fun assertCleartextDefaultDenied() {
        val application=context.packageManager.getApplicationInfo(context.packageName,0)
        assertEquals("Installed application must deny cleartext by default",0,
            application.flags and ApplicationInfo.FLAG_USES_CLEARTEXT_TRAFFIC)
        val policy=NetworkSecurityPolicy.getInstance()
        assertFalse("Process policy must deny cleartext by default",policy.isCleartextTrafficPermitted)
        assertFalse("Loopback has no platform-wide exception",policy.isCleartextTrafficPermitted("127.0.0.1"))
    }

    private fun exercise(websocket:Boolean):Unit=runBlocking {
        assertCleartextDefaultDenied()
        val server=ServerSocket(0,1,InetAddress.getByName("127.0.0.1"))
        val activeSocket=AtomicReference<Socket?>()
        val fixtureFailure=AtomicReference<Throwable?>()
        var worker:Thread?=null
        val connection=PahoMqttConnection()
        try {
            val scheme=if(websocket)"ws" else "tcp"
            val path=if(websocket)"/mqtt" else ""
            val profile=BrokerProfile("cleartext-policy-fixture","$scheme://127.0.0.1:${server.localPort}$path",
                listOf(ZigbeeNetwork("fixture","Loopback fixture","alpha")),allowInsecureLocal=false)
            val unconsented=PahoMqttConnection()
            try {
                var rejected=false
                try {withTimeout(2000){unconsented.connect(profile,null)}}
                catch(_:IllegalArgumentException){rejected=true}
                assertTrue("Local cleartext requires explicit profile consent",rejected)
                assertFalse(unconsented.connected)
            }finally{unconsented.close()}
            server.soTimeout=300
            try {
                server.accept().use { fail("Unconsented profile opened a socket") }
            }catch(_:SocketTimeoutException){ /* No connection reached the listener. */ }
            server.soTimeout=5000
            worker=thread(isDaemon=true,name="instrumented-mqtt-loopback") {
                try {
                    server.accept().use { socket->
                        activeSocket.set(socket);socket.soTimeout=5000
                        val input=socket.getInputStream();val output=socket.getOutputStream()
                        if(websocket)upgradeWebSocket(input,output)
                        fun receive()=readPacket(if(websocket)ByteArrayInputStream(readWebSocket(input)) else input)
                        fun send(header:Int,body:ByteArray) {
                            val bytes=packet(header,body)
                            if(websocket)writeWebSocket(output,bytes) else {output.write(bytes);output.flush()}
                        }
                        val connect=receive();check(connect.first==0x10)
                        DataInputStream(ByteArrayInputStream(connect.second)).use { payload->
                            check(payload.readUTF()=="MQTT");check(payload.readUnsignedByte()==4)
                            check(payload.readUnsignedByte()==2) // Clean session, no fixture credentials.
                            check(payload.readUnsignedShort()==30)
                            check(payload.readUTF().startsWith("openvimar-"));check(payload.available()==0)
                        }
                        send(0x20,byteArrayOf(0,0))
                        val subscribe=receive();check(subscribe.first==0x82)
                        val subscription=DataInputStream(ByteArrayInputStream(subscribe.second))
                        val subscriptionId=subscription.readUnsignedShort();check(subscriptionId!=0)
                        check(subscription.readUTF()=="alpha/#");check(subscription.readUnsignedByte()==1)
                        check(subscription.available()==0)
                        send(0x90,byteArrayOf((subscriptionId shr 8).toByte(),subscriptionId.toByte(),1))
                        send(0x31,utf8("alpha/bridge/devices")+"[]".toByteArray(Charsets.UTF_8))
                        val publish=receive();check(publish.first==0x32) // QoS1, never retained.
                        val publication=DataInputStream(ByteArrayInputStream(publish.second))
                        check(publication.readUTF()=="alpha/bridge/request/device/ota_update/check")
                        val publicationId=publication.readUnsignedShort();check(publicationId!=0)
                        check(publication.readBytes().toString(Charsets.UTF_8)=="{\"id\":\"fixture\"}")
                        send(0x40,byteArrayOf((publicationId shr 8).toByte(),publicationId.toByte()))
                        while(input.read()!=-1){ /* Client explicitly closes its own connection. */ }
                    }
                }catch(failure:Throwable){fixtureFailure.set(failure)}
                finally{activeSocket.set(null)}
            }
            withTimeout(10000) {
                connection.connect(profile.copy(allowInsecureLocal=true),null)
                assertTrue("Consented local transport must establish a session",connection.connected)
                connection.subscribe(listOf("alpha/#"))
                val signal=connection.events.first()
                assertTrue(signal is MqttSignal.Message)
                val message=(signal as MqttSignal.Message).value
                assertEquals("alpha/bridge/devices",message.topic)
                assertEquals("[]",message.payload.toString(Charsets.UTF_8));assertTrue(message.retained)
                connection.publish("alpha/bridge/request/device/ota_update/check","{\"id\":\"fixture\"}".toByteArray(Charsets.UTF_8))
                connection.disconnect();assertFalse(connection.connected)
            }
            assertCleartextDefaultDenied()
        }finally{
            try{connection.close()}finally{
                server.close()
                worker?.join(2000)
                if(worker?.isAlive==true){activeSocket.get()?.close();worker?.join(1000)}
            }
        }
        assertFalse("Loopback fixture must exit after client cleanup",worker?.isAlive==true)
        fixtureFailure.get()?.let { throw AssertionError("Loopback MQTT fixture failed",it) }
    }

    private fun upgradeWebSocket(input:InputStream,output:OutputStream) {
        val bytes=ByteArrayOutputStream()
        while(!bytes.toString("US-ASCII").endsWith("\r\n\r\n")){
            val next=input.read();check(next>=0&&bytes.size()<8192);bytes.write(next)
        }
        val request=bytes.toString("US-ASCII");check(request.startsWith("GET /mqtt HTTP/1.1\r\n"))
        val key=request.lines().single{it.startsWith("Sec-WebSocket-Key:",true)}.substringAfter(':').trim()
        val accept=Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-1")
            .digest((key+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").toByteArray(Charsets.US_ASCII)))
        output.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"+
            "Sec-WebSocket-Accept: $accept\r\nSec-WebSocket-Protocol: mqtt\r\n\r\n").toByteArray(Charsets.US_ASCII))
        output.flush()
    }
    private fun utf8(value:String)=ByteArrayOutputStream().also{DataOutputStream(it).writeUTF(value)}.toByteArray()
    private fun packet(header:Int,body:ByteArray):ByteArray {
        val output=ByteArrayOutputStream();output.write(header);var remaining=body.size
        do {
            var digit=remaining%128;remaining/=128
            if(remaining>0)digit=digit or 128
            output.write(digit)
        }while(remaining>0)
        output.write(body);return output.toByteArray()
    }
    private fun readPacket(input:InputStream):Pair<Int,ByteArray> {
        val header=input.read();check(header>=0);var length=0;var scale=1
        do {
            val digit=input.read();check(digit>=0&&scale<=128*128*128)
            length+=(digit and 127)*scale;scale*=128
        }while(digit and 128!=0)
        check(length<=1024*1024)
        val body=ByteArray(length);DataInputStream(input).readFully(body)
        return header to body
    }
    private fun readWebSocket(input:InputStream):ByteArray {
        val data=DataInputStream(input);check(data.readUnsignedByte()==0x82)
        val flags=data.readUnsignedByte();check(flags and 128!=0)
        val size=when(val encoded=flags and 127){126->data.readUnsignedShort();127->error("Fixture frame exceeds bound");else->encoded}
        val mask=ByteArray(4);data.readFully(mask)
        val bytes=ByteArray(size);data.readFully(bytes)
        for(index in bytes.indices)bytes[index]=(bytes[index].toInt() xor mask[index%4].toInt()).toByte()
        return bytes
    }
    private fun writeWebSocket(output:OutputStream,bytes:ByteArray) {
        output.write(0x82)
        if(bytes.size<126)output.write(bytes.size)
        else {output.write(126);output.write(bytes.size shr 8);output.write(bytes.size and 255)}
        output.write(bytes);output.flush()
    }
}
