package org.openvimar.updater;

import android.content.pm.ApplicationInfo;
import android.security.NetworkSecurityPolicy;
import android.test.InstrumentationTestCase;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.PublicKey;
import java.security.spec.X509EncodedKeySpec;
import java.util.*;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import kotlin.Result;
import kotlin.Unit;
import kotlin.coroutines.Continuation;
import kotlin.coroutines.CoroutineContext;
import kotlin.coroutines.intrinsics.CoroutineSingletons;
import kotlin.jvm.functions.Function2;
import kotlinx.serialization.json.Json;
import no.nordicsemi.android.mcumgr.McuMgrScheme;
import no.nordicsemi.android.mcumgr.response.McuMgrResponse;
import org.json.JSONObject;
import org.openvimar.updater.ble.*;
import org.openvimar.updater.core.*;

/** Java keeps the cross-APK test harness independent of optimized-away Kotlin convenience helpers. */
@SuppressWarnings("deprecation")
public final class ReleaseRuntimeContractTest extends InstrumentationTestCase {
    public void testTypedCheckpointKeepsItsPersistedSchemaAndUncertainReset() throws Exception {
        String raw="{\"schemaVersion\":1,\"bundleDigest\":\""+repeat("ab",32)+"\",\"bleAddress\":\"AA:BB:CC:DD:EE:FF\","
            +"\"phase\":\"FINAL_RESET_INTENT\",\"ackOffset\":0,\"resetAcknowledged\":false,\"targetUid\":[\"11223344\",\"55667788\"],"
            +"\"runtimeIdentity\":{\"protocol\":2,\"model\":\"VIMAR30805\",\"layoutVersion\":2,\"uid\":[\"11223344\",\"55667788\"],"
            +"\"loaderSha256\":\"\",\"typedLoader\":{\"kind\":\"common-code44k-anchor-v1\",\"sha256\":\""+repeat("12",32)+"\"},"
            +"\"anchorSha256\":\""+repeat("34",32)+"\"}}";
        Checkpoint value=Json.Default.decodeFromString(Checkpoint.Companion.serializer(),raw);
        String encoded=Json.Default.encodeToString(Checkpoint.Companion.serializer(),value);
        JSONObject observed=new JSONObject(encoded);
        assertEquals("FINAL_RESET_INTENT",observed.getString("phase"));
        assertFalse(observed.optBoolean("resetAcknowledged",false));
        assertEquals("11223344",observed.getJSONArray("targetUid").getString(0));
        JSONObject identity=observed.getJSONObject("runtimeIdentity");
        assertEquals(repeat("12",32),identity.getJSONObject("typedLoader").getString("sha256"));
        assertEquals(repeat("34",32),identity.getString("anchorSha256"));
        assertNotNull(Json.Default.decodeFromString(Checkpoint.Companion.serializer(),encoded));
    }

    public void testNordicIdentityReflectionAndStrictWireRetainTheirContract() throws Exception {
        byte[] digest=new byte[32];Arrays.fill(digest,(byte)0x12);
        byte[] anchor=new byte[32];Arrays.fill(anchor,(byte)0x34);
        RuntimeIdentityResponse legacy=wire(map("protocol",1,"model","VIMAR30805","layout",2,
            "uid",Arrays.asList(0x11223344L,0x55667788L),"loader_sha256",digest),RuntimeIdentityResponse.class,0x8040,1,0);
        assertEquals(Long.valueOf(1),legacy.protocol);assertEquals("VIMAR30805",legacy.model);
        assertEquals(Arrays.asList(0x11223344L,0x55667788L),legacy.uid);assertTrue(Arrays.equals(digest,legacy.loader_sha256));
        JSONObject original=identityJson(legacy.identity());
        assertEquals("11223344",original.getJSONArray("uid").getString(0));
        RuntimeIdentityV2Response typed=wire(map("protocol",2,"model","VIMAR30805","layout",2,
            "uid",Arrays.asList(0x11223344L,0x55667788L),"loader",map("kind","common-code44k-anchor-v1","digest",digest,"anchor_sha256",anchor)),
            RuntimeIdentityV2Response.class,0x8040,1,1);
        assertEquals(Long.valueOf(2),typed.protocol);assertNotNull(typed.loader);
        assertEquals(repeat("34",32),identityJson(typed.identity()).getString("anchorSha256"));
        boolean refused=false;
        try{wire(map("protocol",2,"model","foreign","layout",2,"uid",Arrays.asList(1L,2L),
            "loader",map("kind","common-code44k-anchor-v1","digest",digest,"anchor_sha256",anchor)),
            RuntimeIdentityV2Response.class,0x8040,1,1).identity();}catch(IllegalArgumentException expected){refused=true;}
        assertTrue("A malformed identity cannot become authority after optimization",refused);
    }

    public void testCustomRecoveryAndPairingReflectionRequireExplicitAcknowledgment() throws Exception {
        RecoveryBootHistoryResponse history=wire(map("protocol",1,"record_size",88,"capacity",6,"current_image",1,
            "sequence",0,"pending_reason",0,"state",map("initialized",true,"loaded_valid",true,"storage_valid",true,
                "load_rc",0,"decode_rc",0,"save_rc",0,"view_rc",0),"entries",Collections.emptyList()),RecoveryBootHistoryResponse.class,0x8041,1,0);
        assertEquals(Long.valueOf(88),history.record_size);assertEquals(Long.valueOf(6),history.capacity);
        assertNotNull(history.state);assertNotNull(history.history());assertEquals(0,history.entries.size());
        MigrationBootResponse migration=wire(map("accepted",true),MigrationBootResponse.class,0x8042,3,0);
        assertEquals(Boolean.TRUE,migration.accepted);assertEquals("ACKNOWLEDGED",migration.acknowledgement().name());
        ZigbeePairingReadResponse discovery=wire(map("protocol",1,"duration",120,"forget",true),ZigbeePairingReadResponse.class,0x8043,1,0);
        assertEquals(Long.valueOf(120),discovery.duration);assertEquals(Boolean.TRUE,discovery.forget);assertNotNull(discovery.capabilities());
        ZigbeePairingWriteResponse accepted=wire(map("accepted",true),ZigbeePairingWriteResponse.class,0x8043,3,0);
        assertEquals(Boolean.TRUE,accepted.accepted);assertEquals("ACKNOWLEDGED",accepted.acknowledgement().name());
        boolean refused=false;
        try{wire(map("accepted","true"),ZigbeePairingWriteResponse.class,0x8043,3,0).acknowledgement();}
        catch(Exception expected){refused=true;}
        assertTrue("Mapper coercion must not authorize an invalid acknowledgment",refused);
    }

    public void testUnsupportedOptionalZipMethodsRejectBeforeCodecLinking() throws Exception {
        for(int method:new int[]{20,93,95}){
            boolean refused=false;
            try{PackageReader.INSTANCE.read(new ByteArrayInputStream(rawCompressionMethod(method)));}
            catch(IllegalArgumentException expected){refused=true;}
            assertTrue("Unsupported compression must fail validation before loading a codec",refused);
        }
    }

    public void testSignedSyntheticPackagesStillRequireTheirOriginalTrustAnchor() throws Exception {
        PublicKey legacy=fixtureKey("synthetic-public.der");
        try(InputStream input=getInstrumentation().getContext().getAssets().open("synthetic-update.zip")){
            assertNotNull(PackageValidator.INSTANCE.validate(PackageReader.INSTANCE.read(input),legacy,"9.0.0"));
        }
        PublicKey common=fixtureKey("synthetic-common-v3-public.der");
        try(InputStream input=getInstrumentation().getContext().getAssets().open("synthetic-common-v3.zip")){
            assertNotNull(CommonPackageValidator.INSTANCE.validate(CommonPackageReader.INSTANCE.read(input),common,"9.0.0"));
        }
        boolean refused=false;
        try(InputStream input=getInstrumentation().getContext().getAssets().open("synthetic-update.zip")){
            PackageValidator.INSTANCE.validate(PackageReader.INSTANCE.read(input),common,"9.0.0");
        }catch(IllegalArgumentException expected){refused=true;}
        assertTrue("Optimized package admission must still refuse the wrong signer",refused);
    }

    public void testPlatformCleartextDefaultRemainsDisabled(){
        int flags=getInstrumentation().getTargetContext().getApplicationInfo().flags;
        assertEquals(0,flags&ApplicationInfo.FLAG_USES_CLEARTEXT_TRAFFIC);
        assertFalse(NetworkSecurityPolicy.getInstance().isCleartextTrafficPermitted());
        assertFalse(NetworkSecurityPolicy.getInstance().isCleartextTrafficPermitted("127.0.0.1"));
    }
    public void testConsentedRealPahoTcpPreservesConnectSubscribeReceiveAndPublish() throws Exception {exerciseMqtt(false);}
    public void testConsentedRealPahoWebSocketPreservesConnectSubscribeReceiveAndPublish() throws Exception {exerciseMqtt(true);}

    private void exerciseMqtt(boolean websocket) throws Exception {
        testPlatformCleartextDefaultRemainsDisabled();
        ServerSocket server=new ServerSocket(0,1,InetAddress.getByName("127.0.0.1"));
        AtomicReference<Socket> active=new AtomicReference<>();AtomicReference<Throwable> failure=new AtomicReference<>();
        Thread worker=null;PahoMqttConnection connection=new PahoMqttConnection();
        String uri=(websocket?"ws":"tcp")+"://127.0.0.1:"+server.getLocalPort()+(websocket?"/mqtt":"");
        List<ZigbeeNetwork> networks=Collections.singletonList(new ZigbeeNetwork("fixture","Loopback fixture","alpha"));
        try{
            PahoMqttConnection unconsented=new PahoMqttConnection();
            boolean refused=false;
            try{await(c->unconsented.connect(new BrokerProfile("fixture",uri,networks,false,"Fixture"),null,c));}
            catch(IllegalArgumentException expected){refused=true;}finally{unconsented.close();}
            assertTrue("An insecure profile requires explicit local consent",refused);
            server.setSoTimeout(300);
            try(Socket unexpected=server.accept()){fail("Unconsented profile opened a connection");}catch(SocketTimeoutException expected){}
            server.setSoTimeout(5000);
            worker=new Thread(()->{
                try(Socket socket=server.accept()){
                    active.set(socket);socket.setSoTimeout(5000);
                    InputStream input=socket.getInputStream();OutputStream output=socket.getOutputStream();
                    if(websocket)upgradeWebSocket(input,output);
                    Packet connect=receive(input,websocket);check(connect.header==0x10);
                    DataInputStream body=new DataInputStream(new ByteArrayInputStream(connect.body));
                    check(body.readUTF().equals("MQTT"));check(body.readUnsignedByte()==4);check(body.readUnsignedByte()==2);
                    check(body.readUnsignedShort()==30);check(body.readUTF().startsWith("openvimar-"));check(body.available()==0);
                    send(output,websocket,0x20,new byte[]{0,0});
                    Packet subscribe=receive(input,websocket);check(subscribe.header==0x82);
                    body=new DataInputStream(new ByteArrayInputStream(subscribe.body));int id=body.readUnsignedShort();
                    check(body.readUTF().equals("alpha/#"));check(body.readUnsignedByte()==1);check(body.available()==0);
                    send(output,websocket,0x90,new byte[]{(byte)(id>>8),(byte)id,1});
                    ByteArrayOutputStream retained=new ByteArrayOutputStream();DataOutputStream retainedData=new DataOutputStream(retained);
                    retainedData.writeUTF("alpha/bridge/devices");retainedData.write("[]".getBytes(StandardCharsets.UTF_8));
                    send(output,websocket,0x31,retained.toByteArray());
                    Packet publish=receive(input,websocket);check(publish.header==0x32);
                    body=new DataInputStream(new ByteArrayInputStream(publish.body));
                    check(body.readUTF().equals("alpha/bridge/request/device/ota_update/check"));id=body.readUnsignedShort();
                    byte[] payload=new byte[body.available()];body.readFully(payload);check(new String(payload,StandardCharsets.UTF_8).equals("{\"id\":\"fixture\"}"));
                    send(output,websocket,0x40,new byte[]{(byte)(id>>8),(byte)id});
                    while(input.read()!=-1){}
                }catch(Throwable error){failure.set(error);}finally{active.set(null);}
            },"optimized-mqtt-loopback");worker.setDaemon(true);worker.start();
            await(c->connection.connect(new BrokerProfile("fixture",uri,networks,true,"Fixture"),null,c));
            assertTrue(connection.getConnected());await(c->connection.subscribe(Collections.singletonList("alpha/#"),c));
            AtomicReference<MqttSignal> received=new AtomicReference<>();
            try{await(c->connection.getEvents().collect((value,continuation)->{received.set(value);throw new FirstMessage();},c));}
            catch(FirstMessage expected){}
            assertTrue(received.get() instanceof MqttSignal.Message);
            MqttMessageEnvelope message=((MqttSignal.Message)received.get()).getValue();
            assertEquals("alpha/bridge/devices",message.getTopic());assertTrue(message.getRetained());
            assertEquals("[]",new String(message.getPayload(),StandardCharsets.UTF_8));
            await(c->connection.publish("alpha/bridge/request/device/ota_update/check","{\"id\":\"fixture\"}".getBytes(StandardCharsets.UTF_8),c));
            await(connection::disconnect);assertFalse(connection.getConnected());testPlatformCleartextDefaultRemainsDisabled();
        }finally{
            connection.close();server.close();
            if(worker!=null){worker.join(2000);if(worker.isAlive()){Socket socket=active.get();if(socket!=null)socket.close();worker.join(1000);}}
        }
        assertFalse("Loopback fixture must exit",worker!=null&&worker.isAlive());
        if(failure.get()!=null)throw new AssertionError("Loopback fixture failed",failure.get());
    }

    private interface SuspendCall {Object invoke(Continuation<? super Unit> continuation);}
    private static final CoroutineContext EMPTY_CONTEXT=new CoroutineContext(){
        @Override public <E extends Element>E get(Key<E> key){return null;}
        @Override public <R>R fold(R initial,Function2<? super R,? super Element,? extends R> operation){return initial;}
        @Override public CoroutineContext plus(CoroutineContext other){return other;}
        @Override public CoroutineContext minusKey(Key<?> key){return this;}
    };
    private static void await(SuspendCall call) throws Exception {
        CountDownLatch finished=new CountDownLatch(1);AtomicReference<Object> result=new AtomicReference<>();
        Object immediate=call.invoke(new Continuation<Unit>(){
            @Override public CoroutineContext getContext(){return EMPTY_CONTEXT;}
            @Override public void resumeWith(Object value){result.set(value);finished.countDown();}
        });
        if(immediate==CoroutineSingletons.COROUTINE_SUSPENDED){
            if(!finished.await(10,TimeUnit.SECONDS))throw new AssertionError("Asynchronous backend operation exceeded its bound");
            immediate=result.get();
        }
        if(immediate instanceof Result.Failure){
            Throwable failure=((Result.Failure)immediate).exception;
            if(failure instanceof Exception)throw (Exception)failure;
            throw new AssertionError("Backend operation failed",failure);
        }
    }
    private static final class FirstMessage extends RuntimeException {}
    private static void check(boolean value){if(!value)throw new AssertionError("Unexpected loopback MQTT packet");}
    private static final class Packet {final int header;final byte[] body;Packet(int header,byte[] body){this.header=header;this.body=body;}}
    private static Packet receive(InputStream input,boolean websocket) throws IOException {
        InputStream data=websocket?new ByteArrayInputStream(readWebSocket(input)):input;
        int header=data.read();check(header>=0);int size=0,scale=1,digit;
        do{digit=data.read();check(digit>=0&&scale<=128*128*128);size+=(digit&127)*scale;scale*=128;}while((digit&128)!=0);
        check(size<=1024*1024);byte[] body=new byte[size];new DataInputStream(data).readFully(body);return new Packet(header,body);
    }
    private static void send(OutputStream output,boolean websocket,int header,byte[] body) throws IOException {
        ByteArrayOutputStream packet=new ByteArrayOutputStream();packet.write(header);int size=body.length;
        do{int digit=size%128;size/=128;if(size>0)digit|=128;packet.write(digit);}while(size>0);
        packet.write(body);byte[] bytes=packet.toByteArray();
        if(websocket){output.write(0x82);if(bytes.length<126)output.write(bytes.length);else{output.write(126);output.write(bytes.length>>8);output.write(bytes.length&255);}}
        output.write(bytes);output.flush();
    }
    private static byte[] readWebSocket(InputStream input) throws IOException {
        DataInputStream data=new DataInputStream(input);check(data.readUnsignedByte()==0x82);int flags=data.readUnsignedByte();check((flags&128)!=0);
        int encoded=flags&127;check(encoded!=127);int size=encoded==126?data.readUnsignedShort():encoded;check(size<65536);
        byte[] mask=new byte[4];data.readFully(mask);byte[] bytes=new byte[size];data.readFully(bytes);
        for(int i=0;i<size;i++)bytes[i]=(byte)(bytes[i]^mask[i%4]);return bytes;
    }
    private static void upgradeWebSocket(InputStream input,OutputStream output) throws Exception {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        while(!bytes.toString("US-ASCII").endsWith("\r\n\r\n")){int next=input.read();check(next>=0&&bytes.size()<8192);bytes.write(next);}
        String request=bytes.toString("US-ASCII");check(request.startsWith("GET /mqtt HTTP/1.1\r\n"));String key=null;
        for(String line:request.split("\r\n"))if(line.regionMatches(true,0,"Sec-WebSocket-Key:",0,18))key=line.substring(18).trim();
        check(key!=null);String accept=Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-1")
            .digest((key+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").getBytes(StandardCharsets.US_ASCII)));
        output.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: "+accept+"\r\nSec-WebSocket-Protocol: mqtt\r\n\r\n").getBytes(StandardCharsets.US_ASCII));output.flush();
    }
    private static Map<String,Object> map(Object...pairs){
        Map<String,Object> result=new LinkedHashMap<>();for(int i=0;i<pairs.length;i+=2)result.put((String)pairs[i],pairs[i+1]);return result;
    }
    private static <T extends McuMgrResponse>T wire(Map<String,Object> values,Class<T> type,int group,int operation,int command) throws Exception {
        ByteArrayOutputStream encoded=new ByteArrayOutputStream();writeCbor(encoded,values);
        byte[] payload=encoded.toByteArray(),header=new byte[]{(byte)(8|operation),0,(byte)(payload.length>>8),(byte)payload.length,(byte)(group>>8),(byte)group,0,(byte)command};
        ByteArrayOutputStream packet=new ByteArrayOutputStream();packet.write(header);packet.write(payload);
        return McuMgrResponse.buildResponse(McuMgrScheme.BLE,packet.toByteArray(),type);
    }
    // Independent bounded fixture encoding avoids keeping an unused transport encoder API.
    private static void writeCbor(ByteArrayOutputStream output,Object value) throws IOException {
        if(value instanceof Map){
            Map<?,?> entries=(Map<?,?>)value;writeHead(output,5,entries.size());
            for(Map.Entry<?,?> entry:entries.entrySet()){writeCbor(output,entry.getKey());writeCbor(output,entry.getValue());}
        }else if(value instanceof List){
            List<?> values=(List<?>)value;writeHead(output,4,values.size());for(Object entry:values)writeCbor(output,entry);
        }else if(value instanceof String){
            byte[] bytes=((String)value).getBytes(StandardCharsets.UTF_8);writeHead(output,3,bytes.length);output.write(bytes);
        }else if(value instanceof byte[]){
            byte[] bytes=(byte[])value;writeHead(output,2,bytes.length);output.write(bytes);
        }else if(value instanceof Boolean){output.write(((Boolean)value)?0xf5:0xf4);}
        else if(value instanceof Number){writeHead(output,0,((Number)value).longValue());}
        else throw new AssertionError("Unsupported synthetic CBOR fixture value");
    }
    private static void writeHead(ByteArrayOutputStream output,int major,long value){
        check(value>=0&&value<=0xffffffffL);
        if(value<24){output.write((major<<5)|(int)value);return;}
        int count=value<=255?1:value<=65535?2:4;output.write((major<<5)|(count==1?24:count==2?25:26));
        for(int shift=(count-1)*8;shift>=0;shift-=8)output.write((int)(value>>shift)&255);
    }
    private static String repeat(String value,int count){StringBuilder result=new StringBuilder();for(int i=0;i<count;i++)result.append(value);return result.toString();}
    private static JSONObject identityJson(RuntimeIdentity value) throws Exception{return new JSONObject(Json.Default.encodeToString(RuntimeIdentity.Companion.serializer(),value));}
    private PublicKey fixtureKey(String name) throws Exception {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();try(InputStream input=getInstrumentation().getContext().getAssets().open(name)){
            byte[] chunk=new byte[4096];int count;while((count=input.read(chunk))!=-1)bytes.write(chunk,0,count);
        }
        return KeyFactory.getInstance("EC").generatePublic(new X509EncodedKeySpec(bytes.toByteArray()));
    }
    private static byte[] rawCompressionMethod(int method) throws IOException {
        byte[] data="{}".getBytes(StandardCharsets.UTF_8);ByteArrayOutputStream output=new ByteArrayOutputStream();
        try(ZipOutputStream zip=new ZipOutputStream(output)){
            ZipEntry entry=new ZipEntry("manifest.json");entry.setMethod(ZipEntry.STORED);entry.setSize(data.length);entry.setCompressedSize(data.length);
            CRC32 crc=new CRC32();crc.update(data);entry.setCrc(crc.getValue());zip.putNextEntry(entry);zip.write(data);zip.closeEntry();
        }
        byte[] bytes=output.toByteArray();int central=-1;
        for(int i=0;i<bytes.length-3;i++)if(bytes[i]==0x50&&bytes[i+1]==0x4b&&bytes[i+2]==1&&bytes[i+3]==2){check(central==-1);central=i;}
        check(central>=0);bytes[8]=(byte)method;bytes[9]=0;bytes[central+10]=(byte)method;bytes[central+11]=0;return bytes;
    }
}
