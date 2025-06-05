
from flask import Flask, redirect, request, jsonify, abort
import logging
from proxy_service import ProxyService
from url_manager import URLManager
from config import BotConfig
import os

app = Flask(__name__)
logger = logging.getLogger(__name__)

# Initialize proxy service
try:
    config = BotConfig.from_env()
    proxy_service = ProxyService(
        secret_key=getattr(config, 'proxy_secret_key', 'telegram_bot_proxy_secret'),
        proxy_domain=getattr(config, 'proxy_domain', 'localhost:5000')
    )
except Exception as e:
    logger.error(f"Failed to initialize proxy service: {e}")
    proxy_service = None

@app.route('/')
def hello_world():
    return 'Free Storage Server Working'

@app.route('/file/<filename>/<proxy_id>')
def proxy_file(filename, proxy_id):
    """Proxy endpoint to redirect to actual GitHub file"""
    if not proxy_service:
        abort(503, "Proxy service not available")
    
    try:
        # Decode the proxy URL to get original GitHub URL
        original_url = proxy_service.decode_url(proxy_id)
        
        if not original_url:
            logger.warning(f"Invalid proxy request: {filename}/{proxy_id}")
            abort(404, "File not found or invalid proxy URL")
        
        # Validate that it's a GitHub URL
        if not proxy_service.validate_github_url(original_url):
            logger.warning(f"Invalid GitHub URL in proxy: {original_url}")
            abort(400, "Invalid file URL")
        
        # Log the request for analytics
        client_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
        logger.info(f"Proxy request: {filename} from {client_ip}")
        
        # Redirect to the actual GitHub file
        return redirect(original_url, code=302)
        
    except Exception as e:
        logger.error(f"Proxy error for {filename}/{proxy_id}: {e}")
        abort(500, "Internal server error")

@app.route('/api/info/<filename>/<proxy_id>')
def file_info(filename, proxy_id):
    """API endpoint to get file information without redirecting"""
    if not proxy_service:
        return jsonify({"error": "Proxy service not available"}), 503
    
    try:
        original_url = proxy_service.decode_url(proxy_id)
        
        if not original_url:
            return jsonify({"error": "Invalid proxy URL"}), 404
        
        return jsonify({
            "filename": filename,
            "original_url": original_url,
            "proxy_url": f"{request.host_url}file/{filename}/{proxy_id}",
            "status": "active"
        })
        
    except Exception as e:
        logger.error(f"Info error for {filename}/{proxy_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "proxy_service": "available" if proxy_service else "unavailable",
        "message": "Free Storage Server Working"
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "File not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

# Remove the if __name__ == "__main__" block since gunicorn will handle the app
