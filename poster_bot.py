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

# Price per size, in cents. Based on typical Etsy unframed poster pricing
# (bigger sizes carry a bigger margin, since print cost doesn't scale as
# fast as what buyers are willing to pay for a larger piece).
SIZE_PRICES_CENTS = {
    "8x10": 1799,
    "11x14": 2299,
    "12x16": 2699,
    "18x24": 3499,
    "24x36": 4499,
}
DEFAULT_PRICE_CENTS = 2499  # fallback if a size isn't in the table above
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

CITIES = [
    "New York City", "Tokyo", "Paris", "London", "Chicago", "Dubai",
    "Singapore", "Hong Kong", "Sydney", "San Francisco", "Seattle",
    "Miami", "Los Angeles", "Shanghai", "Toronto", "Vancouver",
    "Barcelona", "Rome", "Amsterdam", "Venice",
]

CARS = [
    "matte black sports car", "silver sports coupe", "classic vintage convertible",
    "sleek electric hypercar", "chrome muscle car", "midnight blue grand tourer",
    "white minimalist sports sedan", "matte grey rally car", "red vintage roadster",
    "carbon fiber supercar",
]

TIMES = [
    "golden hour", "blue hour at dusk", "neon-lit night", "sunrise",
    "foggy overcast morning", "dramatic storm light", "twilight",
]

STYLES = [
    "cinematic lighting, 8k detail", "ultra-realistic architectural photography",
    "moody atmospheric tone", "high contrast dramatic shading",
    "minimalist composition", "vibrant color grading",
]

CITY_SCENES = [
    "aerial view of a rooftop overlooking",
    "waterfront view of",
    "street-level view looking up at",
    "wide panoramic skyline of",
]

CAR_SCENES = [
    "on an empty highway",
    "parked on a coastal road",
    "in a minimalist studio setting",
    "on a rain-slicked city street",
]


def build_prompt() -> str:
    """Build a photo-realistic poster prompt from independent detail lists.
    Combining city/car x scene x time x style gives thousands of distinct
    combinations, so daily posters stay fresh instead of repeating a short
    fixed list."""
    if random.random() < 0.5:
        subject = f"{random.choice(CITY_SCENES)} the {random.choice(CITIES)} skyline"
    else:
        subject = f"{random.choice(CARS)} {random.choice(CAR_SCENES)}"

    time_of_day = random.choice(TIMES)
    style = random.choice(STYLES)
    return f"ultra-realistic {subject}, {time_of_day}, {style}, photorealistic"


def generate_image(prompt: str) -> bytes:
    """Call fal.ai Flux Schnell to generate an image, return raw image bytes.
    Uses a tall portrait size so the art fills poster shapes edge-to-edge
    (most poster sizes are close to a 3:4 or 2:3 portrait ratio)."""
    resp = requests.post(
        "https://fal.run/fal-ai/flux/schnell",
        headers={"Authorization": f"Key {FAL_KEY}"},
        json={"prompt": prompt, "image_size": "portrait_4_3", "num_images": 1},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    image_url = data["images"][0]["url"]

    img_resp = requests.get(image_url, timeout=60)
    img_resp.raise_for_status()
    return img_resp.content


def get_variant_ids() -> dict:
    """Look up Printify's variant IDs for our blueprint/provider that match
    the sizes we want to sell (e.g. '8x10', '18x24'), so we never have to
    hunt for these numbers by hand. Returns {size: variant_id}."""
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
    matched = {}
    for v in variants:
        norm = normalize(v["title"])
        if norm in wanted and norm not in matched:
            matched[norm] = v["id"]

    missing = wanted - set(matched.keys())
    if missing:
        print(f"Warning: couldn't find these sizes in Printify's catalog: {missing}")
    if not matched:
        raise RuntimeError(
            "No matching variants found. Check BLUEPRINT_ID, PRINT_PROVIDER_ID, "
            "and DESIRED_SIZES."
        )

    print(f"Matched sizes -> variant IDs: {matched}")
    return matched


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


def create_and_publish_product(image_id: str, title: str, description: str, variant_map: dict, shop_id: str):
    """Create a poster product on Printify with the uploaded image, then publish to Etsy.
    variant_map is {size_string: variant_id}."""
    variant_ids = list(variant_map.values())

    product_payload = {
        "title": title,
        "description": description,
        "blueprint_id": BLUEPRINT_ID,
        "print_provider_id": PRINT_PROVIDER_ID,
        "variants": [
            {
                "id": vid,
                "price": SIZE_PRICES_CENTS.get(size, DEFAULT_PRICE_CENTS),
                "is_enabled": True,
            }
            for size, vid in variant_map.items()
        ],
        "print_areas": [
            {
                "variant_ids": variant_ids,
                "placeholders": [
                    {
                        "position": "front",
                        "images": [
                            # scale slightly above 1 so the image fully
                            # bleeds to the poster's edges with no white
                            # border, even if the aspect ratio doesn't
                            # match a given size exactly
                            {"id": image_id, "x": 0.5, "y": 0.5, "scale": 1.05, "angle": 0}
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


POSTERS_PER_RUN = 15  # how many new posters to publish each time this runs


def main():
    shop_id = get_shop_id()
    variant_map = get_variant_ids()

    used_prompts = set()
    successes = 0
    failures = 0

    for i in range(1, POSTERS_PER_RUN + 1):
        print(f"\n--- Poster {i} of {POSTERS_PER_RUN} ---")

        # avoid generating the same prompt twice within the same run
        prompt = build_prompt()
        attempts = 0
        while prompt in used_prompts and attempts < 10:
            prompt = build_prompt()
            attempts += 1
        used_prompts.add(prompt)

        try:
            print(f"Generating image for prompt: {prompt}")
            image_bytes = generate_image(prompt)

            file_name = f"poster_{i}.png"
            image_id = upload_image_to_printify(image_bytes, file_name)
            print(f"Uploaded to Printify, image ID: {image_id}")

            title = prompt.split(",")[0].title() + " - Fine Art Print"
            description = (
                f"A striking, ultra-realistic wall art print. {prompt}. "
                "Printed on premium poster paper, ready to frame."
            )

            create_and_publish_product(image_id, title, description, variant_map, shop_id)
            successes += 1
        except Exception as e:
            # one failed poster shouldn't stop the rest of the day's batch
            print(f"Poster {i} failed: {e}")
            failures += 1

    print(f"\nDone. {successes} posters published, {failures} failed.")


if __name__ == "__main__":
    main()
