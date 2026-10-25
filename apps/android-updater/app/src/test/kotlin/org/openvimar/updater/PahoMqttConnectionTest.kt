package org.openvimar.updater

import java.io.*
import java.net.*
import java.security.MessageDigest
import java.util.Base64
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import org.junit.Assert.*
import org.junit.Test

/** Loopback-only MQTT/WS fixture. Never reads user settings or contacts a real broker. */
class PahoMqttConnectionTest {
    @Test fun tlsUsesPlatformTrustAndHostnameValidationWithoutReconnectOrOfflineReplay() {
        val connection=PahoMqttConnection()
        val profile=BrokerProfile("test","ssl://broker.example",listOf(ZigbeeNetwork("a","A","alpha")))
        val options=connection.options(profile,null)
        assertTrue(options.isHttpsHostnameVerificationEnabled);assertNotNull(options.socketFactory)
        assertFalse(options.isAutomaticReconnect);assertTrue(options.isCleanSession)
        assertEquals(4,options.mqttVersion)
        connection.close()
    }
    @Test fun realPahoTcpConnectSubscribePublishAndReceive()=exercise(false)
    @Test fun realPahoWebSocketConnectSubscribePublishAndReceive()=exercise(true)
    @Test fun bareIpv4AddressReachesRealPahoConnectSubscribePublishAndReceive()=exercise(false,bareTcpAddress=true)
    private fun exercise(websocket:Boolean,bareTcpAddress:Boolean=false):Unit=runBlocking {
        val server=ServerSocket(0,1,InetAddress.getByName("127.0.0.1"));server.soTimeout=5000
        val failure=AtomicReference<Throwable?>()
        val worker=thread(isDaemon=true,name="fixture-mqtt-loopback") {
            try { server.accept().use { socket ->
                socket.soTimeout=5000;val input=socket.getInputStream();val output=socket.getOutputStream()
                if(websocket) {
                    val bytes=ByteArrayOutputStream()
                    while(!bytes.toString("US-ASCII").endsWith("\r\n\r\n")) { val ch=input.read();check(ch>=0 && bytes.size()<8192);bytes.write(ch) }
                    val request=bytes.toString("US-ASCII");check(request.startsWith("GET /mqtt HTTP/1.1"))
                    val key=request.lines().single { it.startsWith("Sec-WebSocket-Key:",true) }.substringAfter(':').trim()
                    val accept=Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-1").digest((key+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").toByteArray()))
                    output.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: $accept\r\nSec-WebSocket-Protocol: mqtt\r\n\r\n").toByteArray());output.flush()
                }
                fun receive():Pair<Int,ByteArray> = readPacket(if(websocket)ByteArrayInputStream(readWs(input)) else input)
                fun send(header:Int,body:ByteArray) { val packet=packet(header,body);if(websocket)writeWs(output,packet) else {output.write(packet);output.flush()} }
                check(receive().first shr 4==1);send(0x20,byteArrayOf(0,0))
                val subscribe=receive();check(subscribe.first shr 4==8)
                send(0x90,byteArrayOf(subscribe.second[0],subscribe.second[1],1))
                send(0x31,utf8("alpha/bridge/devices")+"[]".toByteArray())
                val publish=receive();check(publish.first==0x32) // QoS1, never retained.
                val b=DataInputStream(ByteArrayInputStream(publish.second));val topic=b.readUTF();check(topic=="alpha/bridge/request/device/ota_update/check")
                val packetId=b.readUnsignedShort();check(b.readBytes().toString(Charsets.UTF_8)=="{\"id\":\"fixture\"}")
                send(0x40,byteArrayOf((packetId shr 8).toByte(),packetId.toByte()))
                while(input.read()!=-1) { /* close initiated explicitly by client */ }
            }} catch(e:Throwable) { failure.set(e) }
        }
        val connection=PahoMqttConnection()
        try { withTimeout(10000) {
            val scheme=if(websocket)"ws" else "tcp";val path=if(websocket)"/mqtt" else ""
            val address=if(bareTcpAddress)"127.0.0.1:${server.localPort}" else "$scheme://127.0.0.1:${server.localPort}$path"
            connection.connect(BrokerProfile("loopback",address,listOf(ZigbeeNetwork("a","A","alpha")),true),null)
            connection.subscribe(listOf("alpha/#"))
            val received=connection.events.first() as MqttSignal.Message
            assertEquals("alpha/bridge/devices",received.value.topic);assertTrue(received.value.retained)
            assertEquals("[]",received.value.payload.toString(Charsets.UTF_8))
            connection.publish("alpha/bridge/request/device/ota_update/check","{\"id\":\"fixture\"}".toByteArray())
            connection.disconnect();assertFalse(connection.connected)
        }} finally { connection.close();server.close();worker.join(2000) }
        assertFalse("Loopback broker did not exit",worker.isAlive)
        failure.get()?.let { throw AssertionError("Loopback broker failed",it) }
    }
    private fun utf8(value:String)=ByteArrayOutputStream().also { DataOutputStream(it).writeUTF(value) }.toByteArray()
    private fun packet(header:Int,body:ByteArray):ByteArray {
        val out=ByteArrayOutputStream();out.write(header);var n=body.size
        do { var digit=n%128;n/=128;if(n>0)digit=digit or 128;out.write(digit) }while(n>0)
        out.write(body);return out.toByteArray()
    }
    private fun readPacket(input:InputStream):Pair<Int,ByteArray> {
        val header=input.read();check(header>=0);var length=0;var scale=1
        do { val digit=input.read();check(digit>=0 && scale<=128*128*128);length+=(digit and 127)*scale;scale*=128 }while(digit and 128!=0)
        check(length<=1024*1024);val body=input.readNBytes(length);check(body.size==length);return header to body
    }
    private fun readWs(input:InputStream):ByteArray {
        check(input.read()==0x82);val flags=input.read();check(flags and 128!=0);var size=flags and 127
        if(size==126)size=(input.read() shl 8) or input.read()
        check(size<65536);val mask=input.readNBytes(4);check(mask.size==4);val bytes=input.readNBytes(size);check(bytes.size==size)
        return bytes.mapIndexed { i,b -> (b.toInt() xor mask[i%4].toInt()).toByte() }.toByteArray()
    }
    private fun writeWs(output:OutputStream,bytes:ByteArray) {
        output.write(0x82);if(bytes.size<126)output.write(bytes.size)else {output.write(126);output.write(bytes.size shr 8);output.write(bytes.size and 255)}
        output.write(bytes);output.flush()
    }
}
