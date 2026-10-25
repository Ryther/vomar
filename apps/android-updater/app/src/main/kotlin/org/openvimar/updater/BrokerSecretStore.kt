package org.openvimar.updater

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.io.*
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Secret values are deliberately absent from data-class toString/copy/export. */
internal class BrokerCredentials(val username:String?, val password:CharArray):Closeable {
    override fun close() { password.fill('\u0000') }
    override fun toString() = "BrokerCredentials(<redacted>)"
}

internal object BrokerSecretEnvelope {
    private const val MAX_SECRET = 16384
    private fun aad(profile:BrokerProfile) = ("openvimar-mqtt-v1\u0000"+profile.id+"\u0000"+profile.validated().serverUri).toByteArray(Charsets.UTF_8)
    fun seal(key:SecretKey,profile:BrokerProfile,secret:BrokerCredentials):ByteArray {
        profile.validated()
        val plain=ByteArrayOutputStream().also { bytes -> DataOutputStream(bytes).use { out ->
            out.writeBoolean(secret.username!=null); secret.username?.let { out.writeUTF(it) }
            out.writeUTF(String(secret.password))
        }}.toByteArray()
        require(plain.size<=MAX_SECRET) { "Credentials exceed local storage bound" }
        try {
            val cipher=Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE,key); cipher.updateAAD(aad(profile))
            require(cipher.iv.size==12)
            return byteArrayOf(1)+cipher.iv+cipher.doFinal(plain)
        } finally { plain.fill(0) }
    }
    fun open(key:SecretKey,profile:BrokerProfile,envelope:ByteArray):BrokerCredentials {
        profile.validated(); require(envelope.size in 29..(MAX_SECRET+29) && envelope[0].toInt()==1) { "Invalid encrypted credential envelope" }
        val cipher=Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE,key,GCMParameterSpec(128,envelope.copyOfRange(1,13))); cipher.updateAAD(aad(profile))
        val plain=cipher.doFinal(envelope,13,envelope.size-13)
        try { return DataInputStream(ByteArrayInputStream(plain)).use { input ->
            val username=if(input.readBoolean())input.readUTF() else null
            val password=input.readUTF().toCharArray()
            if(input.available()!=0) { password.fill('\u0000'); throw IllegalArgumentException("Trailing encrypted credential data") }
            BrokerCredentials(username,password)
        }} finally { plain.fill(0) }
    }
}

/** Only ciphertext is persisted; Android backup/export is disabled by the app. */
internal class BrokerSecretStore(context:Context) {
    private val preferences=context.applicationContext.getSharedPreferences("mqtt-secrets-v1",Context.MODE_PRIVATE)
    private val alias="org.openvimar.updater.mqtt.aes-gcm.v1"
    @Synchronized private fun key():SecretKey {
        val store=KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias,null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true).setKeySize(256).build())
        }.generateKey()
    }
    fun encrypt(profile:BrokerProfile,secret:BrokerCredentials):String = android.util.Base64.encodeToString(BrokerSecretEnvelope.seal(key(),profile,secret),android.util.Base64.NO_WRAP)
    fun save(profile:BrokerProfile,secret:BrokerCredentials) {
        check(preferences.edit().putString(profile.id,encrypt(profile,secret)).commit()) { "Unable to save encrypted broker credentials" }
    }
    fun load(profile:BrokerProfile):BrokerCredentials? {
        val value=preferences.getString(profile.id,null) ?: return null
        // Never silently discard an authentication failure or copy credentials to a new endpoint.
        return BrokerSecretEnvelope.open(key(),profile,android.util.Base64.decode(value,android.util.Base64.NO_WRAP))
    }
    fun has(profile:BrokerProfile)=preferences.contains(profile.id)
    fun remove(profile:BrokerProfile) { check(preferences.edit().remove(profile.id).commit()) }
}
