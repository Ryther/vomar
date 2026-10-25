package org.openvimar.updater.core

class FakeStore(var checkpoint:Checkpoint?=null):SessionStore {
    var failSave=false
    var corrupt=false
    val saved=mutableListOf<Checkpoint>()
    var boundary:(String)->Unit={}
    override suspend fun load(bundleDigest:String,address:String):Checkpoint? { boundary("load.before"); if(corrupt) error("Corrupt session"); return checkpoint.also { boundary("load.after") } }
    override suspend fun save(checkpoint:Checkpoint) { boundary("save.before"); if(failSave) error("Disk full"); this.checkpoint=checkpoint; saved+=checkpoint; boundary("save.after") }
}
class FakeTransport(private val pkg:ValidatedPackage,var remote:RemoteImages):BleTransport {
    val calls=mutableListOf<String>()
    var closeFailure:Exception?=null
    var completedUploads=0
    var ack=ResetAck.ACKNOWLEDGED
    var boundary:(String)->Unit={}
    var afterAck:suspend()->Unit={}
    var uploadOffsets=listOf(1)
    private suspend fun call(name:String,action:suspend()->Unit) { boundary("$name.before"); calls+=name; action(); boundary("$name.after") }
    override suspend fun connect(address:String)=call("connect") {}
    override suspend fun images():RemoteImages { call("images") {}; return remote }
    override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit)=call("upload") {
        val migration=data.contentEquals(pkg.migration)
        remote=remote.copy(primary=null)
        uploadOffsets.forEach { onAck(it) }
        remote=remote.copy(primary=RemoteImage(if(migration) pkg.manifest.migration.signedRegionSha256 else pkg.manifest.main.signedRegionSha256,true,true))
        completedUploads++
        afterAck()
    }
    override suspend fun close() { calls+="close";closeFailure?.let {throw it} }
    override suspend fun reset():ResetAck {
        call("reset") {
            if(remote.primary?.hash==pkg.manifest.migration.signedRegionSha256) remote=remote.copy(recovery=RemoteImage(pkg.manifest.targetRecoverySignedHash,true,true))
        }
        return ack
    }
}
