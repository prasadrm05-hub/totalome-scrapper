import os
import base64
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from playwright.async_api import async_playwright

app = FastAPI()

async def scrape_site(retailer: str, query: str, debug: bool = False, shot: bool = False):
    results, logs = [], []
    page_state = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36")
        page = await context.new_page()

        async def log_console(msg):
            logs.append(msg.text)
        page.on("console", log_console)

        url = None
        if retailer == "homedepot":
            url = f"https://www.homedepot.com/s/{query}"
        elif retailer == "wayfair":
            url = f"https://www.wayfair.com/keyword.php?keyword={query}"
        else:
            return {"error": f"Unsupported retailer {retailer}"}

        await page.goto(url, timeout=60000)

        # Collect diagnostics
        page_state["title"] = await page.title()
        page_state["readyState"] = await page.evaluate("document.readyState")
        body_visible = await page.evaluate("document.querySelector('body')?.offsetParent !== null")
        page_state["bodyVisibility"] = "visible" if body_visible else "hidden"

        # Handle cookie banners
        try:
            await page.click("button:has-text('Accept All')", timeout=3000)
        except:
            pass
        try:
            await page.click("button:has-text('Accept Cookies')", timeout=3000)
        except:
            pass

        # Scroll
        await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        await page.wait_for_timeout(3000)

        # Selectors
        selectors = {
            "homedepot": ".product-pod--title a",
            "wayfair": "a.ProductCard-link, div.pl-BaseCard-Title a"
        }

        if retailer in selectors:
            items = await page.query_selector_all(selectors[retailer])
            for item in items[:10]:
                title = await item.inner_text()
                href = await item.get_attribute("href")
                results.append({"title": title.strip(), "url": href})

        # Screenshot
        screenshot_b64 = None
        if shot:
            screenshot_bytes = await page.screenshot(full_page=True)
            screenshot_b64 = "data:image/png;base64," + base64.b64encode(screenshot_bytes).decode()

        await browser.close()

    if debug:
        return {
            "request": {"retailer": retailer, "query": query},
            "page": page_state,
            "logs": logs[:15],
            "count": len(results),
            "sample": results[:3],
            "screenshot": screenshot_b64 if shot else None
        }
    return results

@app.get("/search")
async def search(q: str = Query(...), retailer: str = Query(...), debug: bool = False, shot: bool = False):
    try:
        return await scrape_site(retailer, q, debug, shot)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/")
async def root():
    return {"message": "Totalome scraper ready", "docs": "/docs", "health": "/health"}
