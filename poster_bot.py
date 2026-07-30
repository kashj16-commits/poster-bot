"""
poster_bot.py
Daily automation: generate a poster image with fal.ai (Flux), upload it to
Printify, and publish it as a live listing on your connected Etsy shop.

Required environment variables (set these as GitHub Secrets):
  FAL_KEY            - your fal.ai API key
  PRINTIFY_API_TOKEN - your Printify API token
  PRINTIFY_SHOP_ID   - your Printify shop ID (find via /shops.json)
"""

import os
import random
import base64
import requests

# ---------- CONFIG: your Printify setup ----------
BLUEPRINT_ID = 282          # Printify poster blueprint ID
PRINT_PROVIDER_ID = 99      # print provider ID for that blueprint
DESIRED_SIZES = ["8x10", "11x14", "12x16", "18x24", "24x36"]  # sizes to sell
RETAIL_PRICE_CENTS = 2999   # what YOU charge the customer, in cents ($29.99)
# -------------------------------------------------------------------------

FAL_KEY = os.environ["FAL_KEY"]
PRINTIFY_TOKEN = os.environ["PRINTIFY_API_TOKEN"]


def get_shop_id() -> str:
    """Automatically find the connected Etsy shop's ID, so you never have to
    go hunting for this number by hand."""
    resp = requests.get(
        "https://api.printify.com/v1/shops.json",
        headers={"Authorization": f"Bearer {PRINTIFY_TOKEN}"},
        timeout=60,
    )
    resp.raise_for_status()
    shops = resp.json()

    if not shops:
        raise RuntimeError(
            "No shops found on this Printify account. Make sure your Etsy "
            "store is connected in Printify's 'Manage My Stores' page."
        )

    # Prefer a shop whose sales channel is Etsy if there's more than one shop.
    etsy_shops = [s for s in shops if "etsy" in s.get("sales_channel", "").lower()]
    chosen = etsy_shops[0] if etsy_shops else shops[0]

    print(f"Using shop: {chosen['title']} (id: {chosen['id']})")
    return str(chosen["id"])

PROMPTS = [
    "ultra-realistic New York City skyline at golden hour, cinematic lighting, 8k detail",
    "sleek matte black sports car, studio lighting, minimalist background, photorealistic",
    "Tokyo skyline at night, neon reflections, ultra-realistic, cinematic",
    "elegant silver sports car on empty highway at sunset, photorealistic, dramatic lighting",
    "Chicago skyline from the lake, blue hour, ultra-realistic architectural photography",
    "vintage convertible on coastal road, golden hour, photorealistic detail",
]


def generate_image(prompt: str) -> bytes:
    """Call fal.ai Flux Schnell to generate an image, return raw image bytes."""
    resp = requests.post(
        "https://fal.run/fal-ai/flux/schnell",
        headers={"Authorization": f"Key {FAL_KEY}"},
        json={"prompt": prompt, "image_size": "square_hd", "num_images": 1},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    image_url = data["images"][0]["url"]

    img_resp = requests.get(image_url, timeout=60)
    img_resp.raise_for_status()
    return img_resp.content


def get_variant_ids() -> list:
    """Look up Printify's variant IDs for our blueprint/provider that match
    the sizes we want to sell (e.g. '8x10', '18x24'), so we never have to
    hunt for these numbers by hand."""
    resp = requests.get(
        f"https://api.printify.com/v1/catalog/blueprints/{BLUEPRINT_ID}"
        f"/print_providers/{PRINT_PROVIDER_ID}/variants.json",
        headers={"Authorization": f"Bearer {PRINTIFY_TOKEN}"},
        timeout=60,
    )
    resp.raise_for_status()
    variants = resp.json()["variants"]

    def normalize(size_str: str) -> str:
        # turns '8" x 10"' or '8 x 10 in' or '8x10' all into '8x10'
        digits = "".join(c if c.isdigit() else " " for c in size_str)
        nums = digits.split()
        return "x".join(nums[:2])

    wanted = set(DESIRED_SIZES)
    matched_ids = []
    matched_sizes = []
    for v in variants:
        norm = normalize(v["title"])
        if norm in wanted and norm not in matched_sizes:
            matched_ids.append(v["id"])
            matched_sizes.append(norm)

    missing = wanted - set(matched_sizes)
    if missing:
        print(f"Warning: couldn't find these sizes in Printify's catalog: {missing}")
    if not matched_ids:
        raise RuntimeError(
            "No matching variants found. Check BLUEPRINT_ID, PRINT_PROVIDER_ID, "
            "and DESIRED_SIZES."
        )

    print(f"Matched sizes: {matched_sizes} -> variant IDs {matched_ids}")
    return matched_ids


def upload_image_to_printify(image_bytes: bytes, file_name: str) -> str:
    """Upload image to Printify's media library, return the Printify image ID."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    resp = requests.post(
        "https://api.printify.com/v1/uploads/images.json",
        headers={"Authorization": f"Bearer {PRINTIFY_TOKEN}"},
        json={"file_name": file_name, "contents": b64},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def create_and_publish_product(image_id: str, title: str, description: str, variant_ids: list, shop_id: str):
    """Create a poster product on Printify with the uploaded image, then publish to Etsy."""
    product_payload = {
        "title": title,
        "description": description,
        "blueprint_id": BLUEPRINT_ID,
        "print_provider_id": PRINT_PROVIDER_ID,
        "variants": [
            {"id": vid, "price": RETAIL_PRICE_CENTS, "is_enabled": True}
            for vid in variant_ids
        ],
        "print_areas": [
            {
                "variant_ids": variant_ids,
                "placeholders": [
                    {
                        "position": "front",
                        "images": [
                            {"id": image_id, "x": 0.5, "y": 0.5, "scale": 1, "angle": 0}
                        ],
                    }
                ],
            }
        ],
    }

    create_resp = requests.post(
        f"https://api.printify.com/v1/shops/{shop_id}/products.json",
        headers={"Authorization": f"Bearer {PRINTIFY_TOKEN}"},
        json=product_payload,
        timeout=60,
    )
    create_resp.raise_for_status()
    product_id = create_resp.json()["id"]

    publish_resp = requests.post(
        f"https://api.printify.com/v1/shops/{shop_id}/products/{product_id}/publish.json",
        headers={"Authorization": f"Bearer {PRINTIFY_TOKEN}"},
        json={
            "title": True,
            "description": True,
            "images": True,
            "variants": True,
            "tags": True,
        },
        timeout=60,
    )
    publish_resp.raise_for_status()
    print(f"Published product {product_id} to Etsy.")


def main():
    shop_id = get_shop_id()
    variant_ids = get_variant_ids()

    prompt = random.choice(PROMPTS)
    print(f"Generating image for prompt: {prompt}")
    image_bytes = generate_image(prompt)

    file_name = "poster.png"
    image_id = upload_image_to_printify(image_bytes, file_name)
    print(f"Uploaded to Printify, image ID: {image_id}")

    title = prompt.split(",")[0].title() + " - Fine Art Print"
    description = (
        f"A striking, ultra-realistic wall art print. {prompt}. "
        "Printed on premium poster paper, ready to frame."
    )

    create_and_publish_product(image_id, title, description, variant_ids, shop_id)


if __name__ == "__main__":
    main()
