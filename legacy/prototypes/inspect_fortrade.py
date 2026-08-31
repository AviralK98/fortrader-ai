from playwright.sync_api import sync_playwright


with sync_playwright() as p:

    browser = p.chromium.connect_over_cdp(
        "http://127.0.0.1:9222"
    )

    context = browser.contexts[0]

    page = None

    for candidate in context.pages:
        if "ready.fortrade.com" in candidate.url:
            page = candidate
            break

    if page is None:
        raise RuntimeError("Fortrade tab not found")

    print("Connected:")
    print(page.url)
    print()

    text = page.locator("body").inner_text(
        timeout=10000
    )

    print("========== FORTRADE TEXT ==========")
    print(text)