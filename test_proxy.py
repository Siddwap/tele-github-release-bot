
#!/usr/bin/env python3
"""
Test script to verify proxy functionality
"""
import os
import sys
import logging

# Setup logging first
logging.basicConfig(level=logging.INFO)

try:
    from response_formatter import format_upload_complete_message, get_both_urls
    from bot_integration import get_upload_response_with_proxy, get_url_info
    print("✅ All modules imported successfully")
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

def test_proxy_functionality():
    """Test the proxy service with sample data"""
    print("🧪 Testing Proxy Functionality...")
    print("=" * 50)
    
    # Sample GitHub URL and filename
    sample_github_url = "https://github.com/Siddwap/Video-storage-test-august2023/releases/download/v1.0.0/RWA_Complete_Mathematics_Bilingual_Updated_Book_2025_by_Ankit_Bh.pdf"
    sample_filename = "RWA_Complete_Mathematics_Bilingual_Updated_Book_2025_by_Ankit_Bh.pdf"
    sample_file_size = "15.2 MB"
    
    print(f"📎 Original URL: {sample_github_url}")
    print(f"📁 Filename: {sample_filename}")
    print(f"📊 File Size: {sample_file_size}")
    print()
    
    # Test direct response formatter
    print("🔄 Testing direct response formatter...")
    try:
        formatted_message = format_upload_complete_message(sample_github_url, sample_filename, sample_file_size)
        print("📱 Direct Response:")
        print("-" * 30)
        print(formatted_message)
        print("-" * 30)
    except Exception as e:
        print(f"❌ Direct formatter error: {e}")
    
    print()
    
    # Test bot integration
    print("🔄 Testing bot integration...")
    try:
        bot_response = get_upload_response_with_proxy(sample_github_url, sample_filename, sample_file_size)
        print("🤖 Bot Integration Response:")
        print("-" * 30)
        print(bot_response)
        print("-" * 30)
    except Exception as e:
        print(f"❌ Bot integration error: {e}")
    
    print()
    
    # Test URL data
    print("🔄 Testing URL generation...")
    try:
        url_data = get_both_urls(sample_github_url, sample_filename)
        print("📊 URL Data:")
        for key, value in url_data.items():
            print(f"   {key}: {value}")
    except Exception as e:
        print(f"❌ URL generation error: {e}")
    
    print()
    
    # Test bot integration URL info
    print("🔄 Testing bot integration URL info...")
    try:
        url_info = get_url_info(sample_github_url, sample_filename)
        print("🤖 Bot URL Info:")
        for key, value in url_info.items():
            print(f"   {key}: {value}")
    except Exception as e:
        print(f"❌ Bot URL info error: {e}")
    
    print("\n✅ Test completed!")
    
    # Check if proxy is working
    try:
        url_data = get_both_urls(sample_github_url, sample_filename)
        if url_data.get('has_proxy', False):
            print("🌐 Proxy service is working!")
            print(f"🔗 Proxy URL: {url_data['proxy_url']}")
        else:
            print("⚠️  Proxy service not working. Check configuration:")
            print("   - Ensure PROXY_ENABLED=true in .env")
            print("   - Ensure PROXY_DOMAIN is set correctly")
            print("   - Ensure PROXY_SECRET_KEY is set")
            if url_data.get('error'):
                print(f"   - Error: {url_data['error']}")
    except Exception as e:
        print(f"❌ Proxy check error: {e}")

if __name__ == "__main__":
    test_proxy_functionality()
