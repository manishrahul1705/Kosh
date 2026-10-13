#!/usr/bin/env python3
"""Diagnostic script to test GeM tender access without downloading.

Reports on page accessibility, document link detection, and any security
challenges.

Usage:
    python scripts/test_tender_document_access.py --bid-url "<URL>"

Example:
    python scripts/test_tender_document_access.py \\
        --bid-url "https://bidplus.gem.gov.in/showbidDocument/b_id_123"
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("diagnostic")
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)


def test_url_access(url: str, timeout: float = 30.0) -> dict:
    """Test access to a tender detail page without downloading documents."""
    print()
    print("=" * 70)
    print("GeM TENDER DOCUMENT ACCESS DIAGNOSTIC")
    print("=" * 70)
    print()

    print(f"URL: {url}")
    print()

    # Parse URL
    parsed = urlparse(url)
    print(f"Domain: {parsed.netloc}")
    print(f"Path: {parsed.path}")
    print()

    # Perform request
    print("Fetching page...")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url, headers=headers)

            print(f"✓ HTTP Status: {response.status_code}")
            print(f"  Final URL: {response.url}")
            print(f"  Content-Type: {response.headers.get('content-type', 'not specified')}")
            print()

            # Check for access issues
            html = response.text

            # Detect CAPTCHA
            captcha_indicators = [
                "captcha",
                "verify you are human",
                "robot check",
                "unusual traffic",
                "bot detection",
            ]
            has_captcha = any(ind in html.lower() for ind in captcha_indicators)

            if has_captcha:
                print("⚠️  CAPTCHA/Human Verification Detected")
            else:
                print("✓ No CAPTCHA detected")

            # Detect access denial
            denial_indicators = [
                "access denied",
                "403 forbidden",
                "unauthorized",
                "not allowed",
            ]
            has_denial = any(ind in html.lower() for ind in denial_indicators)

            if has_denial:
                print("⚠️  Access Denial Detected")
            else:
                print("✓ No access denial detected")

            print()

            # Extract page title
            title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
            if title_match:
                print(f"Page Title: {title_match.group(1)}")
            print()

            # Look for document links
            print("Searching for document links...")

            # Common patterns
            link_patterns = [
                (r'href=["\']([^"\']*\.pdf)["\']', 'PDF links'),
                (r'href=["\']([^"\']*\.xlsx?)["\']', 'Excel links'),
                (r'href=["\']([^"\']*\.doc[x]?)["\']', 'Word links'),
                (r'href=["\']([^"\']*\.zip)["\']', 'ZIP links'),
                (r'downloadFile\(["\']([^"\']+)["\']\)', 'JS download functions'),
            ]

            all_links = []
            for pattern, desc in link_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                if matches:
                    print(f"  {desc}: {len(matches)}")
                    all_links.extend(matches)

            # Extract text labels near links (simplified)
            label_patterns = [
                r'Main.*?Bid',
                r'Buyer\s+Added\s+ATC',
                r'Specification',
                r'BOQ',
                r'Bill\s+of\s+Quantities',
                r'Scope\s+of\s+Work',
                r'Corrigendum',
                r'Annexure',
                r'Technical.*?Document',
            ]

            found_labels = set()
            for pattern in label_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                found_labels.update(matches)

            if found_labels:
                print()
                print("Document types detected:")
                for label in sorted(found_labels):
                    print(f"  - {label}")

            print()

            # Check if this is a direct PDF response
            content_type = response.headers.get('content-type', '').lower()
            is_direct_pdf = 'application/pdf' in content_type
            
            if is_direct_pdf:
                # Direct PDF detected - this is the main bid document
                print()
                print("DIRECT PDF DETECTED")
                print("-" * 70)
                print("✓ Content-Type: application/pdf")
                
                # Check PDF magic bytes
                pdf_header = html[:4] if len(html) >= 4 else ""
                is_valid_pdf = pdf_header.startswith("%PDF") or pdf_header.startswith(b"%PDF")
                if is_valid_pdf:
                    print("✓ PDF magic bytes valid (%PDF)")
                else:
                    print("⚠️  PDF header not found - may be invalid")
                
                # Get content length if available
                content_length = response.headers.get('content-length')
                if content_length:
                    size_mb = int(content_length) / (1024 * 1024)
                    print(f"✓ File size: {size_mb:.2f} MB")
                
                print()
                print("=" * 70)
                print("RESULT: ✓ DIRECT MAIN BID PDF DETECTED")
                return {"accessible": True, "documents_found": True, "pdf_direct": True}
            
            elif all_links:
                print(f"Total unique links found: {len(set(all_links))}")
                print()

                # Show first few links
                print("Sample links (first 5):")
                for i, link in enumerate(set(all_links)[:5]):
                    # Make absolute if relative
                    if link.startswith("/"):
                        abs_link = f"https://{parsed.netloc}{link}"
                    elif not link.startswith("http"):
                        abs_link = f"https://{parsed.netloc}/{link}"
                    else:
                        abs_link = link

                    print(f"  {i+1}. {abs_link}")
                
                print()
                print("=" * 70)
                print(f"RESULT: ✓ OK ({len(set(all_links))} document links detected)")
                return {"accessible": True, "documents_found": True, "link_count": len(set(all_links))}
            else:
                print("⚠️  No document links found")
                print()
                print("=" * 70)
                print("RESULT: ⚠️  NO DOCUMENTS (No links detected)")
                return {"accessible": True, "documents_found": False}

            print()
            print("=" * 70)

            if has_captcha:
                print("RESULT: ⚠️  BLOCKED (CAPTCHA/Human verification required)")
                return {"accessible": False, "reason": "CAPTCHA"}
            elif has_denial:
                print("RESULT: ⚠️  BLOCKED (Access denied)")
                return {"accessible": False, "reason": "Access denied"}
            elif response.status_code >= 400:
                print(f"RESULT: ⚠️  ERROR (HTTP {response.status_code})")
                return {"accessible": False, "reason": f"HTTP {response.status_code}"}

    except httpx.TimeoutException:
        print("✗ ERROR: Request timeout")
        return {"accessible": False, "reason": "Timeout"}
    except httpx.ConnectError as e:
        print(f"✗ ERROR: Connection failed - {e}")
        return {"accessible": False, "reason": "Connection failed"}
    except Exception as e:
        print(f"✗ ERROR: {e}")
        return {"accessible": False, "reason": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="Test GeM tender detail page accessibility"
    )
    parser.add_argument(
        "--bid-url",
        type=str,
        required=True,
        help="Full URL to tender detail page (e.g., https://bidplus.gem.gov.in/showbidDocument/b_id_123)",
    )
    args = parser.parse_args()

    result = test_url_access(args.bid_url)
    sys.exit(0 if result.get("accessible") else 1)


if __name__ == "__main__":
    main()
