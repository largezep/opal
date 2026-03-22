"""
get_images.py
=============
Fetches high-resolution public domain images from the NASA Image Library
for use as OPAL episode backgrounds.

Usage:
    python get_images.py "neutron star pulsar nebula"
    python get_images.py "shard cosmology fractal universe"
    python get_images.py  (uses DEFAULT_KEYWORDS below)

Downloads images to OUTPUT_DIR, ready for fusion.py to use.
No API key required. NASA images are public domain.

NASA Image API docs: https://images.nasa.gov/docs/images.nasa.gov_api_docs.pdf
"""

import os
import sys
import json
import requests
import urllib.request
from urllib.parse import quote

# ── CONFIG ──────────────────────────────────────────────
OUTPUT_DIR      = r"C:\OPAL"
MAX_IMAGES      = 8        # how many images to download
MIN_SIZE_KB     = 200      # skip tiny/low-res images
DEFAULT_KEYWORDS = "nebula galaxy deep space cosmic"
# ────────────────────────────────────────────────────────

NASA_SEARCH_URL = "https://images-api.nasa.gov/search"
NASA_ASSET_URL  = "https://images-api.nasa.gov/asset"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}

# Good cosmology search terms to try
COSMOLOGY_SEARCHES = [
    "neutron star",
    "nebula hubble",
    "galaxy deep field",
    "supernova remnant",
    "pulsar",
    "cosmic web",
    "black hole",
    "crab nebula",
    "pillars of creation",
    "james webb telescope",
]


def search_nasa(query, count=10):
    """Search NASA image library and return list of (title, nasa_id) tuples."""
    params = {
        "q": query,
        "media_type": "image",
        "page_size": count,
    }
    try:
        resp = requests.get(NASA_SEARCH_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("collection", {}).get("items", [])
        results = []
        for item in items:
            if not item.get("data") or not item.get("links"):
                continue
            title   = item["data"][0].get("title", "unknown")
            nasa_id = item["data"][0].get("nasa_id", "")
            thumb   = item["links"][0].get("href", "")
            if nasa_id:
                results.append((title, nasa_id, thumb))
        return results
    except Exception as e:
        print(f"  Search error for '{query}': {e}")
        return []


def get_full_res_url(nasa_id):
    """
    Get the highest resolution image URL for a given NASA ID.
    Falls back to thumbnail if full-res unavailable.
    """
    try:
        url = f"{NASA_ASSET_URL}/{quote(nasa_id)}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("collection", {}).get("items", [])

        # Prefer largest TIFF or JPG
        tiffs = [i["href"] for i in items if i["href"].lower().endswith(".tif")]
        jpgs  = [i["href"] for i in items if i["href"].lower().endswith(".jpg")
                 and "~thumb" not in i["href"] and "~small" not in i["href"]]
        large = [i["href"] for i in items if "~large" in i["href"] or "~orig" in i["href"]]

        # Priority: large JPG > any JPG > TIFF (TIFFs are huge)
        if large:
            return large[0]
        if jpgs:
            return jpgs[-1]  # last JPG is usually highest res
        if tiffs:
            return tiffs[0]
        if items:
            return items[0]["href"]
        return None
    except Exception as e:
        print(f"  Asset lookup error for {nasa_id}: {e}")
        return None


def download_image(url, output_path):
    """Download image to output_path. Returns file size in KB."""
    try:
        resp = requests.get(url, headers=HEADERS, stream=True, timeout=30)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(65536):
                f.write(chunk)
        size_kb = os.path.getsize(output_path) // 1024
        return size_kb
    except Exception as e:
        print(f"  Download error: {e}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return 0


def safe_filename(title, nasa_id, ext=".jpg"):
    """Convert title to safe filename."""
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    safe = safe[:50].strip()
    return f"{safe}_{nasa_id[-6:]}{ext}".replace(" ", "_")


def fetch_images(keywords, output_dir, max_images=MAX_IMAGES):
    """
    Main function: search NASA for keywords, download best images.
    """
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n=== GET IMAGES ===\n")
    print(f"  Keywords: {keywords}")
    print(f"  Target:   {max_images} images → {output_dir}\n")

    # Search for each keyword phrase
    all_results = []
    search_terms = keywords.split(",") if "," in keywords else [keywords]

    # Also add some always-good cosmology terms
    for term in search_terms:
        term = term.strip()
        if term:
            print(f"  Searching: '{term}'")
            results = search_nasa(term, count=max_images)
            print(f"    Found {len(results)} results")
            all_results.extend(results)

    if not all_results:
        print("  No results found. Try different keywords.")
        return []

    # Deduplicate by nasa_id
    seen = set()
    unique = []
    for r in all_results:
        if r[1] not in seen:
            seen.add(r[1])
            unique.append(r)

    print(f"\n  Unique images found: {len(unique)}")
    print(f"  Downloading up to {max_images}...\n")

    downloaded = []
    for i, (title, nasa_id, thumb) in enumerate(unique[:max_images]):
        print(f"  [{i+1}/{min(max_images, len(unique))}] {title[:60]}")

        # Get full resolution URL
        full_url = get_full_res_url(nasa_id)
        if not full_url:
            print(f"    Skipping — no full-res URL found")
            continue

        # Determine extension
        ext = ".jpg"
        if full_url.lower().endswith(".tif"):
            ext = ".tif"
        elif full_url.lower().endswith(".png"):
            ext = ".png"

        filename = safe_filename(title, nasa_id, ext)
        output_path = os.path.join(output_dir, filename)

        # Skip if already downloaded
        if os.path.exists(output_path):
            size_kb = os.path.getsize(output_path) // 1024
            print(f"    Already exists ({size_kb}KB) — skipping")
            downloaded.append(output_path)
            continue

        size_kb = download_image(full_url, output_path)
        if size_kb < MIN_SIZE_KB:
            print(f"    Too small ({size_kb}KB) — skipping")
            if os.path.exists(output_path):
                os.remove(output_path)
            continue

        print(f"    ✓ {filename} ({size_kb}KB)")
        downloaded.append(output_path)

    print(f"\n  Downloaded: {len(downloaded)} images")
    print(f"  Location: {output_dir}")
    print(f"\n  Ready for fusion.py\n")
    return downloaded


def main():
    if len(sys.argv) >= 2:
        keywords = " ".join(sys.argv[1:])
    else:
        keywords = DEFAULT_KEYWORDS
        print(f"  No keywords supplied — using default: '{keywords}'")
        print(f"  Usage: python get_images.py \"neutron star pulsar nebula\"\n")

    fetch_images(keywords, OUTPUT_DIR)


if __name__ == "__main__":
    main()
