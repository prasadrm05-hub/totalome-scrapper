from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from urllib.parse import quote_plus
from playwright.async_api import async_playwright

app = FastAPI(title="Totalome Backend (Scraper)", version="0.2.0")

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

async def extract_homedepot(page):
    items = []
    cards = await page.query_selector_all('[data-automation*="product-pod"]')
    for c in cards[:20]:
        title_el = await c.query_selector('[data-automation="product-title"]')
        title = (await title_el.inner_text()).strip() if title_el else None
        price_el = await c.query_selector('[data-automation="product-price"]')
        price = None
        if price_el:
            txt = (await price_el.inner_text()).replace("$","").replace(",","").strip()
            try: price = float(txt.split()[0])
            except: price = None
        link_el = await c.query_selector('a')
        url = await link_el.get_attribute('href') if link_el else None
        if url and url.startswith("/"):
            url = "https://www.homedepot.com" + url
        img_el = await c.query_selector('img')
        image = await img_el.get_attribute('src') if img_el else None
        if title and url:
            items.append(Product(title=title, price=price, image=image, url=url, retailer="homedepot"))
    return items

async def extract_wayfair(page):
    items = []
    cards = await page.query_selector_all('a:has(div[class*="ProductCard"])')
    for a in cards[:20]:
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
    cards = await page.query_selector_all('a:has(article)')
    for a in cards[:20]:
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
                 retailer: str = Query("homedepot", description="homedepot|wayfair|ikea")):
    url = build_search_url(q, retailer)
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)

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
        return [i.model_dump() for i in items]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
