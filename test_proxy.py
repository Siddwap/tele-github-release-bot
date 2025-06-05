
#!/usr/bin/env python3
"""
Test script to verify proxy functionality
"""
import os
import sys
from response_formatter import format_upload_complete_message, get_both_urls

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
    
    # Test URL generation
    print("🔄 Testing URL generation...")
    url_data = get_both_urls(sample_github_url, sample_filename)
    
    print("📊 URL Data:")
    for key, value in url_data.items():
        print(f"   {key}: {value}")
    print()
    
    # Test formatted message
    print("📝 Testing formatted message...")
    formatted_message = format_upload_complete_message(sample_github_url, sample_filename, sample_file_size)
    
    print("📱 Bot Response:")
    print("-" * 30)
    print(formatted_message)
    print("-" * 30)
    
    print("\n✅ Test completed!")
    
    # Check if proxy is working
    if url_data.get('has_proxy', False):
        print("🌐 Proxy service is working!")
        print(f"🔗 Proxy URL: {url_data['proxy_url']}")
    else:
        print("⚠️  Proxy service not working. Check configuration:")
        print("   - Ensure PROXY_ENABLED=true in .env")
        print("   - Ensure PROXY_DOMAIN is set correctly")
        print("   - Ensure PROXY_SECRET_KEY is set")

if __name__ == "__main__":
    test_proxy_functionality()
