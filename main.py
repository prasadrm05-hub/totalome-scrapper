from fastapi import FastAPI, HTTPException, Query, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from urllib.parse import quote_plus
from playwright.async_api import async_playwright
import re, os, asyncio

app = FastAPI(title="Totalome Scraper", version="0.2.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "Totalome scraper ready", "docs": "/docs", "health": "/health"}

@app.get("/health")
def health():
    return {"ok": True}

class Product(BaseModel):
    title: str
    price: Optional[float] = None
    image: Optional[str] = None
    url: str
    retailer: str

MONEY_RE = re.compile(r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)")

def first_money(text: str) -> Optional[float]:
    if not text:
        return None
    m = MONEY_RE.search(text.replace("\u00a0", " "))
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except:
            return None
    return None

def build_search_url(q: str, retailer: str) -> str:
    qenc = quote_plus(q)
    r = retailer.lower()
    if r == "homedepot":
        return f"https://www.homedepot.com/s/{qenc}"
    if r == "wayfair":
        return f"https://www.wayfair.com/keyword.php?keyword={qenc}"
    if r == "ikea":
        return f"https://www.ikea.com/us/en/search?q={qenc}"
    return f"https://duckduckgo.com/?q={qenc}&iax=shopping&ia=shopping"

async def smart_scroll(page, steps: int = 6, delay_ms: int = 400):
    for _ in range(steps):
        await page.mouse.wheel(0, 1500)
        await asyncio.sleep(delay_ms / 1000)

async def extract_homedepot(page):
    items = []
    # Try multiple selectors for product cards
    selectors = [
        '[data-automation*="product-pod"]',
        'div.pod-inner',
        'div.product-pod--padding',
    ]
    cards = []
    for sel in selectors:
        cards = await page.query_selector_all(sel)
        if cards:
            break
    if not cards:
        return items

    for c in cards[:24]:
        title = None; url = None; image = None; price = None

        title_el = await c.query_selector('[data-automation="product-title"], a.product-pod__title, a')
        if title_el:
            try:
                title = (await title_el.inner_text()).strip()
            except:
                pass

        link_el = await c.query_selector('a[href]')
        if link_el:
            url = await link_el.get_attribute('href')
            if url and url.startswith("/"):
                url = "https://www.homedepot.com" + url

        img_el = await c.query_selector('img[src]')
        if img_el:
            image = await img_el.get_attribute('src')

        # price could be spread across spans; grab the card text
        try:
            txt = (await c.inner_text()).strip()
            price = first_money(txt)
        except:
            price = None

        if title and url:
            items.append(Product(title=title, price=price, image=image, url=url, retailer="homedepot"))
    return items

async def extract_wayfair(page):
    items = []
    cards = await page.query_selector_all('a:has(div[class*="ProductCard"]), a.ProductCard, a[data-enzyme-id*="ProductCard"]')
    for a in cards[:24]:
        url = await a.get_attribute('href')
        if url and url.startswith("/"):
            url = "https://www.wayfair.com" + url
        title_el = await a.query_selector('p, span, h2, h3')
        title = (await title_el.inner_text()).strip() if title_el else None
        img_el = await a.query_selector('img')
        image = await img_el.get_attribute('src') if img_el else None
        if title and url:
            items.append(Product(title=title, image=image, url=url, retailer="wayfair"))
    return items

async def extract_ikea(page):
    items = []
    cards = await page.query_selector_all('a:has(article), a[data-testid*="plp-product-card"]')
    for a in cards[:24]:
        url = await a.get_attribute('href')
        if url and url.startswith("/"):
            url = "https://www.ikea.com" + url
        title_el = await a.query_selector('span, p, h3')
        title = (await title_el.inner_text()).strip() if title_el else None
        img_el = await a.query_selector('img')
        image = await img_el.get_attribute('src') if img_el else None
        if title and url:
            items.append(Product(title=title, image=image, url=url, retailer="ikea"))
    return items

@app.get("/search", response_model=List[Product])
async def search(q: str = Query(..., description="e.g. 'modern sofa 72 inch'"),
                 retailer: str = Query("homedepot", description="homedepot|wayfair|ikea"),
                 debug: bool = False):
    url = build_search_url(q, retailer)
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                locale="en-US",
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_selector("body", timeout=15000)
            await smart_scroll(page)

            r = retailer.lower()
            if r == "homedepot":
                items = await extract_homedepot(page)
            elif r == "wayfair":
                items = await extract_wayfair(page)
            elif r == "ikea":
                items = await extract_ikea(page)
            else:
                items = []

            await browser.close()

        data = [i.model_dump() for i in items]
        if debug:
            return {"count": len(data), "url": url, "retailer": retailer, "sample": data[:3]}
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
