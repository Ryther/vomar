package org.openvimar.updater

import android.content.Context
import android.content.ContextWrapper
import android.test.AndroidTestCase

/** Synthetic preferences and credentials; no transport, discovery, or device execution. */
class SavedConnectionPersistenceTest:AndroidTestCase() {
    private fun isolated()=object:ContextWrapper(context){
        override fun getApplicationContext():Context=this
        override fun getSharedPreferences(name:String,mode:Int)=super.getSharedPreferences("saved-connection-test-$name",mode)
    }
    fun testLegacyMigrationAndMetadataRenameKeepTheEncryptedCredentials(){
        val ctx=isolated()
        val prefs=ctx.getSharedPreferences("mqtt-secrets-v1",0);val legacy=ctx.getSharedPreferences("mqtt-profile-v1",0)
        prefs.edit().clear().commit();legacy.edit().clear().commit()
        val original=BrokerProfile("legacy-home","ssl://broker.invalid",listOf(ZigbeeNetwork("original-id","Ground floor","alpha")))
        try {
            legacy.edit().putString("profile",BrokerProfileStore.encode(original)).commit()
            val secrets=BrokerSecretStore(ctx)
            BrokerCredentials("fixture-user","fixture-password".toCharArray()).use{secrets.save(original,it)}
            val ciphertext=prefs.getString(original.id,null)
            val profiles=BrokerProfileStore(ctx)
            assertEquals(original,profiles.load())
            val renamed=original.copy(label="Renamed home")
            profiles.save(renamed)
            assertFalse(legacy.contains("profile"))
            assertEquals(ciphertext,prefs.getString(original.id,null))
            assertEquals(listOf(renamed),profiles.loadAll())
            secrets.load(renamed)!!.use{assertEquals("fixture-user",it.username);assertEquals("fixture-password",String(it.password))}
            val other=BrokerProfile("workshop","ssl://other.invalid",listOf(ZigbeeNetwork("other-id","Garden","beta")))
            profiles.save(other)
            assertEquals(2,profiles.loadAll().size)
            profiles.remove(other.id);assertEquals(listOf(renamed),profiles.loadAll())
            assertFalse(prefs.getString("catalog.v2","")!!.contains("fixture-password"))
            profiles.remove(renamed.id);assertTrue(profiles.loadAll().isEmpty());assertFalse(secrets.has(renamed))
        } finally {prefs.edit().clear().commit();legacy.edit().clear().commit()}
    }
    fun testRejectedReplacementLeavesTheSavedProfileAndSecretUntouched(){
        val ctx=isolated();val prefs=ctx.getSharedPreferences("mqtt-secrets-v1",0)
        prefs.edit().clear().commit();ctx.getSharedPreferences("mqtt-profile-v1",0).edit().clear().commit()
        val original=BrokerProfile("fixture","ssl://broker.invalid",listOf(ZigbeeNetwork("topic","Home","alpha")))
        try {
            val profiles=BrokerProfileStore(ctx);val secrets=BrokerSecretStore(ctx)
            val encrypted=BrokerCredentials("fixture-user","fixture-password".toCharArray()).use{secrets.encrypt(original,it)}
            profiles.save(original,encrypted,true)
            var rejected=false
            try{profiles.save(original.copy(serverUri="ssl://different.invalid"),null,true)}catch(_:IllegalArgumentException){rejected=true}
            assertTrue(rejected);assertEquals(original,profiles.load());assertEquals(encrypted,prefs.getString(original.id,null))
        } finally {prefs.edit().clear().commit()}
    }
}
