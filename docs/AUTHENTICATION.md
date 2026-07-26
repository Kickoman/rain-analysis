# Authentication Guide

This guide covers how to authenticate with the Rain Analysis API using API keys.

## Table of Contents

- [Overview](#overview)
- [Getting Your First API Key](#getting-your-first-api-key)
- [Using API Keys](#using-api-keys)
- [API Key Scopes](#api-key-scopes)
- [Rate Limiting](#rate-limiting)
- [Managing API Keys](#managing-api-keys)
- [Code Examples](#code-examples)
- [Troubleshooting](#troubleshooting)

## Overview

The Rain Analysis API uses API keys for authentication. Every request must include a valid API key in the `X-API-Key` header.

**Key format:** `ra_live_<random_string>`

API keys have:
- **Scopes**: Define what endpoints the key can access
- **Rate limits**: Control request frequency (per minute, hour, day)
- **Expiration**: Optional expiration date
- **Active status**: Can be enabled/disabled

## Getting Your First API Key

### Step 1: Create Admin Key

The first key must be created using the command-line script:

```bash
cd backend
python scripts/create_admin_key.py
```

This will:
1. Prompt for a key name (e.g., "my-admin-key")
2. Generate a secure API key
3. Save it to the database with admin scope
4. Display the key (save it - you won't see it again!)

**Example output:**
```
Created admin API key:
  ID: 1
  Name: my-admin-key
  Key: ra_live_abc123def456...
  Scopes: admin

⚠️  Save this key securely - it won't be displayed again!
```

### Step 2: Create Additional Keys

Once you have an admin key, use it to create keys for different purposes via the API:

```bash
curl -X POST https://api.example.com/admin/keys \
  -H "X-API-Key: ra_live_your_admin_key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "frontend-app",
    "scopes": ["read"],
    "rate_limit_rpm": 60,
    "rate_limit_rph": 1000,
    "rate_limit_rpd": 10000
  }'
```

## Using API Keys

Include your API key in the `X-API-Key` header for every request:

```bash
curl -H "X-API-Key: ra_live_your_key_here" \
     https://api.example.com/health
```

### Successful Response

```json
{
  "status": "healthy",
  "version": "2.0.0"
}
```

### Authentication Failure

**Missing key:**
```json
{
  "error": "unauthorized",
  "message": "API key required",
  "detail": "Include your API key in the X-API-Key header",
  "path": "/health"
}
```

**Invalid key:**
```json
{
  "error": "unauthorized", 
  "message": "Invalid API key",
  "detail": "The provided API key is not valid or has been revoked",
  "path": "/health"
}
```

## API Key Scopes

Scopes control what endpoints an API key can access. A key can have multiple scopes.

### Available Scopes

| Scope | Description | Access Level |
|-------|-------------|--------------|
| `read` | Read-only data access | GET endpoints for sensors, measurements, predictions |
| `write` | Data ingestion and modification | POST/PUT/PATCH/DELETE data endpoints |
| `admin` | Full administrative access | All endpoints including key management |

### Scope Examples

**Read-only key** (for public dashboards):
```json
{
  "name": "public-dashboard",
  "scopes": ["read"],
  "rate_limit_rpm": 30
}
```

**Data ingestion key** (for IoT devices):
```json
{
  "name": "sensor-device-01",
  "scopes": ["write"],
  "rate_limit_rpm": 10,
  "rate_limit_rph": 500
}
```

**Full access key** (for automation):
```json
{
  "name": "automation-script",
  "scopes": ["read", "write", "admin"],
  "rate_limit_rpm": 100
}
```

## Rate Limiting

Rate limits prevent API abuse and ensure fair usage. Limits are configured per-key.

### Rate Limit Types

- **RPM** (Requests Per Minute): Short-term burst protection
- **RPH** (Requests Per Hour): Medium-term usage control
- **RPD** (Requests Per Day): Long-term quota management

### Checking Your Rate Limits

```bash
curl -H "X-API-Key: your_key" \
     https://api.example.com/auth/check
```

**Response:**
```json
{
  "valid": true,
  "key_name": "my-app-key",
  "scopes": ["read", "write"],
  "rate_limits": {
    "rpm": {
      "limit": 60,
      "remaining": 58,
      "reset_at": "2026-07-26T18:31:00Z"
    },
    "rph": {
      "limit": 1000,
      "remaining": 995,
      "reset_at": "2026-07-26T19:00:00Z"
    },
    "rpd": {
      "limit": 10000,
      "remaining": 9987,
      "reset_at": "2026-07-27T00:00:00Z"
    }
  }
}
```

### Rate Limit Exceeded

When you exceed a rate limit:

```json
{
  "error": "rate_limit_exceeded",
  "message": "Rate limit exceeded",
  "detail": "RPM limit of 60 exceeded. Reset at 2026-07-26T18:31:00Z",
  "path": "/health"
}
```

**HTTP Status:** 429 Too Many Requests

**Best practices:**
- Check the `reset_at` timestamp and wait until then
- Implement exponential backoff in your client
- Monitor your usage with `/auth/check`
- Request higher limits if needed (contact admin)

## Managing API Keys

Admin keys can manage other API keys through the admin endpoints.

### Create API Key

```bash
curl -X POST https://api.example.com/admin/keys \
  -H "X-API-Key: ra_live_admin_key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "new-key",
    "scopes": ["read"],
    "rate_limit_rpm": 60,
    "rate_limit_rph": 1000,
    "rate_limit_rpd": 10000,
    "expires_at": "2027-12-31T23:59:59Z"
  }'
```

### List API Keys

```bash
curl -H "X-API-Key: ra_live_admin_key" \
     https://api.example.com/admin/keys
```

**Response:**
```json
{
  "items": [
    {
      "id": 1,
      "name": "my-admin-key",
      "scopes": ["admin"],
      "is_active": true,
      "created_at": "2026-07-26T12:00:00Z",
      "last_used_at": "2026-07-26T18:25:00Z"
    },
    {
      "id": 2,
      "name": "frontend-app",
      "scopes": ["read"],
      "is_active": true,
      "created_at": "2026-07-26T14:00:00Z",
      "last_used_at": "2026-07-26T18:27:00Z"
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 20
}
```

### Update API Key

```bash
curl -X PATCH https://api.example.com/admin/keys/2 \
  -H "X-API-Key: ra_live_admin_key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "frontend-app-v2",
    "rate_limit_rpm": 120
  }'
```

### Revoke API Key

```bash
curl -X DELETE https://api.example.com/admin/keys/2 \
  -H "X-API-Key: ra_live_admin_key"
```

This marks the key as inactive. The key remains in the database for audit purposes but can no longer be used.

## Code Examples

### Python (requests)

```python
import requests

API_KEY = "ra_live_your_key_here"
BASE_URL = "https://api.example.com"

headers = {
    "X-API-Key": API_KEY
}

# Health check
response = requests.get(f"{BASE_URL}/health", headers=headers)
print(response.json())

# Check rate limits
response = requests.get(f"{BASE_URL}/auth/check", headers=headers)
data = response.json()
print(f"Remaining RPM: {data['rate_limits']['rpm']['remaining']}")
```

### Python (httpx with async)

```python
import httpx
import asyncio

API_KEY = "ra_live_your_key_here"
BASE_URL = "https://api.example.com"

async def check_health():
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/health",
            headers={"X-API-Key": API_KEY}
        )
        return response.json()

result = asyncio.run(check_health())
print(result)
```

### JavaScript (fetch)

```javascript
const API_KEY = "ra_live_your_key_here";
const BASE_URL = "https://api.example.com";

async function checkHealth() {
  const response = await fetch(`${BASE_URL}/health`, {
    headers: {
      "X-API-Key": API_KEY
    }
  });
  
  const data = await response.json();
  console.log(data);
}

checkHealth();
```

### JavaScript (axios)

```javascript
const axios = require('axios');

const API_KEY = "ra_live_your_key_here";
const BASE_URL = "https://api.example.com";

const client = axios.create({
  baseURL: BASE_URL,
  headers: {
    "X-API-Key": API_KEY
  }
});

// Health check
client.get('/health')
  .then(response => console.log(response.data))
  .catch(error => console.error(error.response.data));

// Check rate limits
client.get('/auth/check')
  .then(response => {
    const rpm = response.data.rate_limits.rpm;
    console.log(`RPM: ${rpm.remaining}/${rpm.limit}`);
  });
```

### cURL

```bash
# Save your key to an environment variable
export API_KEY="ra_live_your_key_here"

# Health check
curl -H "X-API-Key: $API_KEY" \
     https://api.example.com/health

# Check authentication and rate limits
curl -H "X-API-Key: $API_KEY" \
     https://api.example.com/auth/check

# Create a new API key (admin only)
curl -X POST https://api.example.com/admin/keys \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-key",
    "scopes": ["read"],
    "rate_limit_rpm": 30
  }'
```

## Troubleshooting

### "API key required"

**Problem:** You didn't include the `X-API-Key` header.

**Solution:**
```bash
# Wrong
curl https://api.example.com/health

# Correct
curl -H "X-API-Key: your_key" https://api.example.com/health
```

### "Invalid API key"

**Possible causes:**
1. Typo in the key
2. Key has been revoked
3. Key has expired
4. Using wrong environment (dev key on production)

**Solution:** 
- Double-check the key value
- Verify key status: `GET /admin/keys` (if you have admin access)
- Generate a new key if needed

### "Insufficient scope"

**Problem:** Your key doesn't have the required scope for this endpoint.

**Example:**
```json
{
  "error": "forbidden",
  "message": "Insufficient scope",
  "detail": "This endpoint requires 'admin' scope",
  "path": "/admin/keys"
}
```

**Solution:** Use a key with the appropriate scope, or request scope update from an admin.

### "Rate limit exceeded"

**Problem:** You've exceeded one of your rate limits.

**Solution:**
1. Wait until the `reset_at` time
2. Check your usage: `GET /auth/check`
3. Implement rate limit awareness in your client
4. Request higher limits if legitimately needed

### Key not working after creation

**Problem:** API key works in tests but fails in production.

**Common causes:**
1. Wrong `API_KEYS_SALT` environment variable between environments
2. Database not synced between environments
3. Using test key in production

**Solution:** Ensure each environment has:
- Its own database
- Its own `API_KEYS_SALT` value
- Keys generated in that environment

## Security Best Practices

1. **Never commit keys to version control**
   - Use environment variables
   - Add API keys to `.gitignore`

2. **Rotate keys regularly**
   - Create new keys periodically
   - Revoke old keys after migration

3. **Use minimum required scopes**
   - Don't give `admin` scope unless necessary
   - Prefer `read` for public-facing apps

4. **Monitor key usage**
   - Check `last_used_at` regularly
   - Revoke unused keys

5. **Implement key rotation in your app**
   ```python
   # Good: Handle key rotation gracefully
   PRIMARY_KEY = os.getenv("API_KEY_PRIMARY")
   FALLBACK_KEY = os.getenv("API_KEY_FALLBACK")
   
   def get_api_key():
       # Try primary, fall back if needed
       return PRIMARY_KEY or FALLBACK_KEY
   ```

6. **Use HTTPS in production**
   - Never send API keys over unencrypted HTTP
   - API keys are equivalent to passwords

## Further Reading

- [API Documentation](http://localhost:8000/docs) - Interactive API reference
- [Architecture Guide](architecture.md) - System design and authentication flow
- [Development Guide](DEVELOPMENT.md) - Contributing to the authentication system
