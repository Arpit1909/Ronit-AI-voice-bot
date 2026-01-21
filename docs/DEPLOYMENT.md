# Production Deployment Guide for VPS with PM2 and Caddy

This guide ensures your Ronit AI Coach application works perfectly on a VPS server with PM2 and Caddy.

## Prerequisites

- Ubuntu/Debian VPS
- Python 3.9+
- Node.js (for PM2)
- Caddy installed
- Domain name configured

## Step 1: Install Dependencies

```bash
# Install PM2 globally
npm install -g pm2

# Install Python dependencies
pip install -r requirements.txt
```

## Step 2: Configure Environment Variables

Create a `.env` file in the project root:

```bash
# Core Configuration
ELEVEN_API_KEY=your_elevenlabs_api_key
AGENT_ID=your_agent_id
PORT=5000
ENVIRONMENT=production
DEBUG=false

# Supabase (if using)
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key

# Other configurations...
```

## Step 3: Configure Caddy

1. **Update Caddyfile** (already created in project root):
   - Replace `yourdomain.com` with your actual domain
   - Ensure WebSocket support is enabled (already configured)

2. **Reload Caddy**:
```bash
sudo caddy reload --config /path/to/your/Caddyfile
```

**Important Caddy Settings:**
- ✅ WebSocket upgrade headers configured
- ✅ Long timeout for WebSocket connections (30s)
- ✅ Proper proxy headers (X-Real-IP, X-Forwarded-For, etc.)
- ✅ Health check endpoint configured

## Step 4: Start with PM2

```bash
# Start the application
pm2 start ecosystem.config.js

# Save PM2 configuration
pm2 save

# Setup PM2 to start on system boot
pm2 startup
```

## Step 5: Verify Deployment

1. **Check PM2 Status**:
```bash
pm2 status
pm2 logs ronit-ai-coach
```

2. **Check Health Endpoint**:
```bash
curl http://localhost:5000/health
```

3. **Test WebSocket Connection**:
   - Open your domain in a browser
   - Start a voice session
   - Check browser console for WebSocket connection

## Troubleshooting

### WebSocket Connection Issues

If WebSocket connections fail:

1. **Check Caddy Logs**:
```bash
sudo journalctl -u caddy -f
```

2. **Verify Caddy Configuration**:
   - Ensure `header_up Upgrade "websocket"` is present
   - Check timeout settings (should be 30s+)

3. **Check Flask Logs**:
```bash
pm2 logs ronit-ai-coach
```

### PM2 Issues

1. **Restart Application**:
```bash
pm2 restart ronit-ai-coach
```

2. **Check Memory Usage**:
```bash
pm2 monit
```

3. **View Detailed Logs**:
```bash
pm2 logs ronit-ai-coach --lines 100
```

### Connection Timeout Issues

If connections timeout:

1. **Increase Caddy Timeout** (in Caddyfile):
```
transport http {
    dial_timeout 30s
    response_header_timeout 60s
}
```

2. **Check Gunicorn Timeout** (in gunicorn_config.py):
```python
timeout = 120  # Already configured
```

## Production Checklist

- [ ] Environment variables configured
- [ ] Caddyfile updated with your domain
- [ ] Caddy reloaded and running
- [ ] PM2 started and configured
- [ ] Health endpoint responding
- [ ] WebSocket connections working
- [ ] HTTPS enabled (automatic with Caddy)
- [ ] Logs configured and accessible
- [ ] Auto-restart on failure enabled

## Monitoring

### PM2 Monitoring
```bash
# Real-time monitoring
pm2 monit

# View metrics
pm2 describe ronit-ai-coach
```

### Application Health
```bash
# Check health endpoint
curl https://yourdomain.com/health
```

## Security Notes

1. **Firewall**: Ensure port 80, 443, and 5000 are open
2. **Caddy**: Automatically handles HTTPS/SSL
3. **Flask**: Security headers are automatically set
4. **PM2**: Runs as configured user (not root)

## Performance Optimization

1. **Worker Count**: Automatically set based on CPU cores
2. **Preload App**: Enabled for faster worker startup
3. **Connection Pooling**: Configured in Gunicorn
4. **Static Files**: Served efficiently by Caddy

## Support

If you encounter issues:
1. Check PM2 logs: `pm2 logs ronit-ai-coach`
2. Check Caddy logs: `sudo journalctl -u caddy -f`
3. Verify all environment variables are set
4. Ensure WebSocket support is enabled in Caddy

