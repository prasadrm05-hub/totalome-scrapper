from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from playwright.async_api import async_playwright
import asyncio
import base64

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Totalome scrapper ready", "docs": "/docs", "health": "/health"}

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/search")
async def search(q: str = Query(...), retailer: str = Query(...), debug: bool = False, shot: bool = False):
    url = None
    if retailer == "homedepot":
        url = f"https://www.homedepot.com/s/{q}"
    elif retailer == "wayfair":
        url = f"https://www.wayfair.com/keyword.php?keyword={q}"
    else:
        return JSONResponse(content={"error": "Unsupported retailer"}, status_code=400)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        await page.goto(url, timeout=60000)

        # Retailer-specific waits
        try:
            if retailer == "homedepot":
                await page.wait_for_selector('div[data-testid="product-pod"]', timeout=20000)
            elif retailer == "wayfair":
                await page.wait_for_selector('div[data-enzyme-id="plp-product"]', timeout=20000)
            else:
                await page.wait_for_selector("body", timeout=15000)
        except Exception as e:
            await browser.close()
            return {"error": str(e), "url": url}

        items = []
        if retailer == "homedepot":
            products = await page.query_selector_all('div[data-testid="product-pod"]')
            for pnode in products[:10]:
                title = await pnode.get_attribute("title")
                price = await pnode.inner_text() if pnode else None
                items.append({"title": title, "price": price})
        elif retailer == "wayfair":
            products = await page.query_selector_all('div[data-enzyme-id="plp-product"]')
            for pnode in products[:10]:
                title = await pnode.inner_text() if pnode else None
                items.append({"title": title})

        screenshot_b64 = None
        if shot:
            img = await page.screenshot(full_page=True)
            screenshot_b64 = base64.b64encode(img).decode("utf-8")

        await browser.close()

        return {
            "request": {"q": q, "retailer": retailer, "url": url},
            "count": len(items),
            "items": items,
            "screenshot": f"data:image/png;base64,{screenshot_b64}" if screenshot_b64 else None,
        }
