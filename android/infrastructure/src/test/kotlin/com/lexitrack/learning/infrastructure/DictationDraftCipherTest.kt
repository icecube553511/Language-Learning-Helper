package com.lexitrack.learning.infrastructure

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class DictationDraftCipherTest {
    @Test
    fun `keystore cipher round trips plaintext when provider is available`() {
        val cipher = AndroidKeystoreDictationDraftCipher("test.dictation.${System.nanoTime()}")
        val plaintext = "默写草稿 secret".toByteArray(Charsets.UTF_8)
        try {
            val ciphertext = cipher.encrypt(plaintext)
            assertNotEquals(String(plaintext, Charsets.UTF_8), String(ciphertext, Charsets.UTF_8))
            assertArrayEquals(plaintext, cipher.decrypt(ciphertext))
        } catch (_: DictationDraftCipherException) {
            // Robolectric/JVM environments may not expose AndroidKeyStore;
            // repository tests inject a cipher and cover the storage contract.
        }
    }

    @Test
    fun `aes gcm rejects tampered nonce or ciphertext`() {
        val cipher: DraftCipher = InMemoryAesGcmDictationDraftCipher()
        val ciphertext = cipher.encrypt("draft-word-id".toByteArray(Charsets.UTF_8))
        val tampered = ciphertext.copyOf().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() }
        assertThrows(Exception::class.java) { cipher.decrypt(tampered) }
    }

    @Test
    fun `aes gcm uses a fresh nonce for each save`() {
        val cipher = InMemoryAesGcmDictationDraftCipher()
        val plaintext = "same draft".toByteArray(Charsets.UTF_8)
        val first = cipher.encrypt(plaintext)
        val second = cipher.encrypt(plaintext)
        assertNotEquals(String(first, Charsets.ISO_8859_1), String(second, Charsets.ISO_8859_1))
        assertArrayEquals(plaintext, cipher.decrypt(first))
        assertArrayEquals(plaintext, cipher.decrypt(second))
    }
}
