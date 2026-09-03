package com.lexitrack.learning.infrastructure

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Encryption boundary for the local dictation snapshot.
 *
 * Implementations receive only canonical UTF-8 bytes and return an opaque
 * blob.  The repository persists that blob, never the plaintext.  Keeping
 * this as a small interface lets JVM tests inject a deterministic cipher
 * without weakening the production Keystore path.
 */
interface DraftCipher {
    fun encrypt(plaintext: ByteArray): ByteArray
    fun decrypt(ciphertext: ByteArray): ByteArray
}

/** Backwards-compatible name used by the first draft repository prototype. */
typealias DictationDraftCipher = DraftCipher

class DraftCipherException(message: String, cause: Throwable? = null) :
    RuntimeException(message, cause)

/** Backwards-compatible exception name for existing callers/tests. */
typealias DictationDraftCipherException = DraftCipherException

/** Android Keystore-backed AES-256-GCM cipher. */
class AndroidKeystoreDictationDraftCipher(
    private val alias: String = DEFAULT_KEY_ALIAS,
) : DraftCipher {
    private val keyLock = Any()

    init {
        require(alias.isNotBlank()) { "Android Keystore alias must not be blank" }
    }

    override fun encrypt(plaintext: ByteArray): ByteArray {
        require(plaintext.isNotEmpty()) { "dictation draft plaintext must not be empty" }
        return try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.ENCRYPT_MODE, key())
            // Prefix the random IV; GCM includes its authentication tag in the
            // ciphertext returned by doFinal().
            cipher.iv + cipher.doFinal(plaintext)
        } catch (error: Exception) {
            throw DictationDraftCipherException("无法保护默写草稿", error)
        }
    }

    override fun decrypt(ciphertext: ByteArray): ByteArray {
        if (ciphertext.size <= IV_BYTES + TAG_BYTES) {
            throw DictationDraftCipherException("默写草稿密文无效")
        }
        return try {
            val iv = ciphertext.copyOfRange(0, IV_BYTES)
            val payload = ciphertext.copyOfRange(IV_BYTES, ciphertext.size)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(TAG_BITS, iv))
            cipher.doFinal(payload)
        } catch (error: Exception) {
            throw DictationDraftCipherException("默写草稿密文无效", error)
        }
    }

    private fun key(): SecretKey {
        return synchronized(keyLock) {
            try {
                val store = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
                (store.getKey(alias, null) as? SecretKey) ?: generateKey()
            } catch (error: Exception) {
                throw DictationDraftCipherException("Android 安全存储不可用", error)
            }
        }
    }

    private fun generateKey(): SecretKey {
        return try {
            KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE).apply {
                init(
                    KeyGenParameterSpec.Builder(
                        alias,
                        KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                    )
                        .setKeySize(KEY_BITS)
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                        .build(),
                )
            }.generateKey()
        } catch (error: Exception) {
            throw DictationDraftCipherException("Android 安全存储不可用", error)
        }
    }

    private companion object {
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val DEFAULT_KEY_ALIAS = "lexitrack.dictation.draft.v1"
        const val KEY_BITS = 256
        const val IV_BYTES = 12
        const val TAG_BITS = 128
        const val TAG_BYTES = TAG_BITS / 8
    }
}

/** AES-GCM implementation intended for JVM/Robolectric dependency injection. */
class InMemoryAesGcmDictationDraftCipher(
    private val secretKey: SecretKey = generateTestKey(),
) : DraftCipher {
    override fun encrypt(plaintext: ByteArray): ByteArray {
        require(plaintext.isNotEmpty()) { "dictation draft plaintext must not be empty" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, secretKey)
        return cipher.iv + cipher.doFinal(plaintext)
    }

    override fun decrypt(ciphertext: ByteArray): ByteArray {
        require(ciphertext.size > IV_BYTES + TAG_BYTES) { "dictation draft ciphertext is invalid" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(
            Cipher.DECRYPT_MODE,
            secretKey,
            GCMParameterSpec(TAG_BITS, ciphertext.copyOfRange(0, IV_BYTES)),
        )
        return cipher.doFinal(ciphertext.copyOfRange(IV_BYTES, ciphertext.size))
    }

    private companion object {
        const val IV_BYTES = 12
        const val TAG_BITS = 128
        const val TAG_BYTES = TAG_BITS / 8

        fun generateTestKey(): SecretKey =
            KeyGenerator.getInstance("AES").apply { init(256, SecureRandom()) }.generateKey()
    }
}
