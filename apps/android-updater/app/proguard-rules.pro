# Nordic's consumer rules cover its response package. Project response types
# also expose constructors/fields to Jackson's CBOR reflection. Their classes
# and private implementation can still be renamed and optimized; public members
# remain callable from the separately compiled release instrumentation APK.
-keepclassmembers,allowoptimization class org.openvimar.updater.ble.** extends no.nordicsemi.android.mcumgr.response.McuMgrResponse {
    public <init>();
    public <fields>;
    public <methods>;
}

# Paho 1.2.5 loads the logger reflectively and network factories through its
# META-INF/services resource. Preserve those entry points, not the MQTT graph.
-keep,allowoptimization class org.eclipse.paho.client.mqttv3.logging.JSR47Logger {
    public <init>();
}
-keep,allowoptimization class org.eclipse.paho.client.mqttv3.internal.** implements org.eclipse.paho.client.mqttv3.spi.NetworkModuleFactory {
    public <init>();
}

# Commons Compress exposes optional XZ/Zstandard ZIP codecs. PackageReader
# admits only STORED/DEFLATED before getInputStream; these absent providers
# cannot be reached by an admitted package. Do not hide other missing types.
-dontwarn com.github.luben.zstd.ZstdInputStream
-dontwarn org.tukaani.xz.MemoryLimitException
-dontwarn org.tukaani.xz.SingleXZInputStream
-dontwarn org.tukaani.xz.XZInputStream

# AGP compiles release instrumentation against the target's Kotlin runtime.
# Its separate test APK still calls this null-check ABI after app optimization
# would otherwise inline and remove it. Keep this helper for same-signer tests.
-keep class kotlin.jvm.internal.Intrinsics { *; }

# Separately compiled release tests consume these explicit backend boundaries.
# Retain their member ABI; class names and method bodies remain optimizable.
-keepclassmembers,allowoptimization class kotlinx.serialization.json.Json {
    public static ** Default;
    public *** encodeToString(kotlinx.serialization.SerializationStrategy,java.lang.Object);
    public *** decodeFromString(kotlinx.serialization.DeserializationStrategy,java.lang.String);
}
-keepclassmembers,allowoptimization class org.openvimar.updater.core.PackageReader {
    public static ** INSTANCE;
    public *** read(java.io.InputStream);
}
-keepclassmembers,allowoptimization class org.openvimar.updater.core.CommonPackageReader {
    public static ** INSTANCE;
    public *** read(java.io.InputStream);
}
-keepclassmembers,allowoptimization class org.openvimar.updater.core.PackageValidator {
    public static ** INSTANCE;
    public *** validate(...);
}
-keepclassmembers,allowoptimization class org.openvimar.updater.core.CommonPackageValidator {
    public static ** INSTANCE;
    public *** validate(...);
}
# The public suspend entry points are external roots for same-signer tests;
# do not narrow their continuation argument to app-only coroutine subclasses.
-keep,allowobfuscation class org.openvimar.updater.PahoMqttConnection {
    public <init>();
    public <methods>;
}
-keepclassmembers,allowoptimization class org.openvimar.updater.BrokerProfile {
    public <init>(java.lang.String,java.lang.String,java.util.List,boolean,java.lang.String);
}
-keepclassmembers,allowoptimization class org.openvimar.updater.ZigbeeNetwork {
    public <init>(java.lang.String,java.lang.String,java.lang.String);
}
-keepclassmembers,allowoptimization class org.openvimar.updater.MqttSignal$Message {
    public *** getValue();
}
-keepclassmembers,allowoptimization class org.openvimar.updater.MqttMessageEnvelope {
    public *** getTopic();
    public *** getPayload();
    public *** getRetained();
}
# Kotlin suspend ABI values consumed by the Java continuation in release tests.
-keepclassmembers,allowoptimization class kotlin.coroutines.intrinsics.CoroutineSingletons {
    public static ** COROUTINE_SUSPENDED;
}
-keepclassmembers,allowoptimization class kotlin.Result$Failure {
    public java.lang.Throwable exception;
}
# Keep the explicit suspend/flow interface ABI open to external implementations.
# These interfaces have no implementation bodies and may still be renamed.
-keep,allowobfuscation interface kotlin.coroutines.Continuation { public <methods>; }
-keep,allowobfuscation interface kotlin.coroutines.CoroutineContext { public <methods>; }
-keep,allowobfuscation interface kotlinx.coroutines.flow.Flow { public <methods>; }
-keep,allowobfuscation interface kotlinx.coroutines.flow.FlowCollector { public <methods>; }
