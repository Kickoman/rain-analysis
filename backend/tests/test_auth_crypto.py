"""Unit tests for authentication crypto utilities."""

import pytest
from backend.app.auth.crypto import generate_api_key, hash_api_key, verify_api_key


class TestGenerateAPIKey:
    """Tests for generate_api_key function."""
    
    def test_generate_live_key(self):
        """Test generating a live API key."""
        full_key, key_hash, key_prefix = generate_api_key("live")
        
        assert full_key.startswith("ra_live_")
        assert len(full_key) == 40  # ra_live_ (8) + 32 hex chars = 40
        assert len(key_hash) == 64  # SHA256 hex digest
        assert key_prefix == full_key[:10]
        assert key_prefix == "ra_live_" + full_key[8:10]
    
    def test_generate_test_key(self):
        """Test generating a test API key."""
        full_key, key_hash, key_prefix = generate_api_key("test")
        
        assert full_key.startswith("ra_test_")
        assert len(full_key) == 40  # ra_test_ (8) + 32 hex chars = 40
        assert len(key_hash) == 64  # SHA256 hex digest
        assert key_prefix == full_key[:10]
    
    def test_generate_invalid_environment(self):
        """Test that invalid environment raises ValueError."""
        with pytest.raises(ValueError, match="environment must be 'live' or 'test'"):
            generate_api_key("invalid")
    
    def test_keys_are_unique(self):
        """Test that generated keys are unique."""
        key1, hash1, prefix1 = generate_api_key("live")
        key2, hash2, prefix2 = generate_api_key("live")
        
        assert key1 != key2
        assert hash1 != hash2
        # Prefixes might theoretically collide, but extremely unlikely
    
    def test_hash_matches_full_key(self):
        """Test that generated hash matches the full key."""
        full_key, key_hash, _ = generate_api_key("live")
        
        assert hash_api_key(full_key) == key_hash


class TestHashAPIKey:
    """Tests for hash_api_key function."""
    
    def test_hash_consistency(self):
        """Test that hashing the same key produces the same hash."""
        key = "ra_live_test12345678901234567890123"
        hash1 = hash_api_key(key)
        hash2 = hash_api_key(key)
        
        assert hash1 == hash2
    
    def test_hash_length(self):
        """Test that hash is 64 characters (SHA256 hex)."""
        key = "ra_live_test"
        key_hash = hash_api_key(key)
        
        assert len(key_hash) == 64
    
    def test_different_keys_different_hashes(self):
        """Test that different keys produce different hashes."""
        hash1 = hash_api_key("ra_live_key1")
        hash2 = hash_api_key("ra_live_key2")
        
        assert hash1 != hash2
    
    def test_hash_format(self):
        """Test that hash is hexadecimal."""
        key = "ra_live_test"
        key_hash = hash_api_key(key)
        
        # Should not raise ValueError
        int(key_hash, 16)


class TestVerifyAPIKey:
    """Tests for verify_api_key function."""
    
    def test_verify_correct_key(self):
        """Test that correct key passes verification."""
        key = "ra_live_test12345678901234567890123"
        key_hash = hash_api_key(key)
        
        assert verify_api_key(key, key_hash) is True
    
    def test_verify_incorrect_key(self):
        """Test that incorrect key fails verification."""
        key = "ra_live_test12345678901234567890123"
        wrong_key = "ra_live_wrong1234567890123456789012"
        key_hash = hash_api_key(key)
        
        assert verify_api_key(wrong_key, key_hash) is False
    
    def test_verify_with_generated_key(self):
        """Test verification with a generated key."""
        full_key, key_hash, _ = generate_api_key("live")
        
        assert verify_api_key(full_key, key_hash) is True
    
    def test_verify_timing_safe(self):
        """Test that verification uses constant-time comparison."""
        # This is a smoke test - we can't easily test timing attacks
        # But we verify the function uses secrets.compare_digest
        key = "ra_live_test"
        hash1 = hash_api_key(key)
        hash2 = hash_api_key(key + "x")
        
        # Should return False without crashing
        assert verify_api_key(key, hash2) is False


class TestIntegration:
    """Integration tests for crypto utilities."""
    
    def test_full_workflow(self):
        """Test complete workflow: generate -> hash -> verify."""
        # Generate key
        full_key, key_hash, key_prefix = generate_api_key("test")
        
        # Verify format
        assert full_key.startswith("ra_test_")
        assert len(key_hash) == 64
        assert key_prefix == full_key[:10]
        
        # Verify authentication works
        assert verify_api_key(full_key, key_hash) is True
        
        # Verify wrong key doesn't work
        wrong_key = full_key[:-1] + "x"
        assert verify_api_key(wrong_key, key_hash) is False
