
import os, re, asyncio, random, base64
from typing import List, Optional
from urllib.parse import quote_plus
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

app = FastAPI(title="Totalome Scraper (Stealth)", version="0.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Product(BaseModel):
    title: str
    price: Optional[float] = None
    image: Optional[str] = None
    url: str
    retailer: str

UA_ROTATION = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

MONEY_RE = re.compile(r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)")

def money(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = MONEY_RE.search(text.replace("\u00a0"," "))
    if m:
        try:
            return float(m.group(1).replace(",",""))
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

async def consent_and_unhide(page):
    selectors = [
        "#onetrust-accept-btn-handler",
        "button#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept all')",
        "button:has-text('Accept Cookies')",
        "button:has-text('Accept')",
    ]
    for sel in selectors:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(0.2)
                break
        except:
            pass
    try:
        await page.evaluate("""
            const b = document.body;
            if (!b) return;
            b.style.visibility = 'visible';
            b.style.opacity = '1';
            b.style.overflow = 'auto';
        """)
    except:
        pass

async def smart_scroll(page, steps=8, pause_ms=250):
    for _ in range(steps):
        await page.mouse.wheel(0, 1600)
        await asyncio.sleep(pause_ms/1000)

async def new_browser():
    pw = await async_playwright().start()
    proxy_url = os.getenv("PROXY_URL") or os.getenv("HTTP_PROXY")
    ua = random.choice(UA_ROTATION)
    browser = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
    context_kwargs = dict(user_agent=ua, locale="en-US", timezone_id="America/New_York")
    if proxy_url:
        context_kwargs["proxy"] = {"server": proxy_url}
    context = await browser.new_context(**context_kwargs)
    page = await context.new_page()
    await stealth_async(page)
    return pw, browser, context, page

async def goto_with_retries(page, url: str, retries: int = 2):
    delay_base = 1.2
    last_status = None
    for attempt in range(retries+1):
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            last_status = resp.status if resp else None
        except:
            last_status = None
        if last_status and last_status in (429, 403, 503):
            await asyncio.sleep(delay_base * (attempt+1) + random.uniform(0.5,1.5))
            continue
        return resp
    return resp

async def extract_homedepot(page):
    items = []
    selectors = [
        '[data-testid^="product-pod"]',
        '[data-automation*="product-pod"]',
        'div.product-pod--padding',
        'div.pod-inner',
    ]
    cards = []
    for sel in selectors:
        cards = await page.query_selector_all(sel)
        if cards:
            break
    for c in cards[:24]:
        url = None; title=None; image=None; price=None
        link = await c.query_selector('a[href]')
        if link:
            url = await link.get_attribute('href')
            if url and url.startswith('/'):
                url = 'https://www.homedepot.com' + url
        t = await c.query_selector('[data-automation="product-title"], a[aria-label], a')
        if t:
            try: title = (await t.inner_text()).strip()
            except: pass
        img = await c.query_selector('img[src]')
        if img:
            image = await img.get_attribute('src')
        try:
            price = money(await c.inner_text())
        except:
            price = None
        if title and url:
            items.append({'title': title, 'price': price, 'image': image, 'url': url, 'retailer':'homedepot'})
    return items

async def extract_wayfair(page):
    items = []
    cards = await page.query_selector_all('a:has(div[class*="ProductCard"]), a.ProductCard, a[data-enzyme-id*="ProductCard"], a[href*="/product/"]')
    for a in cards[:24]:
        url = await a.get_attribute('href')
        if url and url.startswith('/'):
            url = 'https://www.wayfair.com' + url
        t = await a.query_selector('p, span, h2, h3')
        title = (await t.inner_text()).strip() if t else None
        img = await a.query_selector('img[src]')
        image = await img.get_attribute('src') if img else None
        if title and url:
            items.append({'title': title, 'image': image, 'url': url, 'retailer': 'wayfair'})
    return items

@app.get('/')
def root():
    return {'message':'Totalome scraper (stealth) ready', 'docs':'/docs', 'health':'/health'}

@app.get('/health')
def health():
    return {'ok': True}

@app.get('/search')
async def search(q: str = Query(...), retailer: str = Query('homedepot'), debug: bool = False, shot: bool = False):
    url = build_search_url(q, retailer)
    logs = []
    try:
        pw, browser, context, page = await new_browser()
        page.on('console', lambda m: logs.append(m.text))

        await goto_with_retries(page, url, retries=2)
        await consent_and_unhide(page)
        await smart_scroll(page, steps=10, pause_ms=300)
        await asyncio.sleep(random.uniform(0.6, 1.2))

        if retailer.lower() == 'homedepot':
            items = await extract_homedepot(page)
        elif retailer.lower() == 'wayfair':
            items = await extract_wayfair(page)
        else:
            items = []

        shot_b64 = None
        if debug or shot:
            try:
                png = await page.screenshot(full_page=True)
                shot_b64 = 'data:image/png;base64,' + base64.b64encode(png).decode()
            except:
                pass

        await browser.close(); await pw.stop()

        if debug:
            title = await page.title() if page else None
            try:
                ready = await page.evaluate('document.readyState')
            except:
                ready = None
            return {'request': {'q': q, 'retailer': retailer, 'url': url},
                    'page': {'title': title, 'readyState': ready},
                    'logs': logs[:15], 'count': len(items), 'sample': items[:3], 'screenshot': shot_b64}
        return items
    except Exception as e:
        raise HTTPException(status_code=500, detail={'error': str(e), 'url': url, 'logs': logs[:10]})
