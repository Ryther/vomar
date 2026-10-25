package org.openvimar.updater

import android.test.AndroidTestCase

/** Synthetic local credentials only; no socket, device, broker, or Android signing key. */
class BrokerKeystoreTest:AndroidTestCase() {
    fun testActualKeystoreEncryptsAndBindsCredentialsWithoutPlaintextPersistence() {
        val profile=BrokerProfile("instrumented-fixture","ssl://broker.invalid",listOf(ZigbeeNetwork("a","A","fixture")))
        val store=BrokerSecretStore(context)
        try {
            BrokerCredentials("synthetic-user","synthetic-secret".toCharArray()).use { store.save(profile,it) }
            val raw=context.getSharedPreferences("mqtt-secrets-v1",0).getString(profile.id,null)!!
            assertFalse(raw.contains("synthetic"))
            store.load(profile)!!.use { assertEquals("synthetic-user",it.username);assertEquals("synthetic-secret",String(it.password)) }
            var rejected=false
            try { store.load(profile.copy(serverUri="ssl://another.invalid")) }catch(_:Exception){rejected=true}
            assertTrue(rejected)
            BrokerCredentials("synthetic-user","synthetic-secret".toCharArray()).use { store.save(profile,it) }
            assertFalse(raw==context.getSharedPreferences("mqtt-secrets-v1",0).getString(profile.id,null))
        } finally { store.remove(profile) }
    }
}
