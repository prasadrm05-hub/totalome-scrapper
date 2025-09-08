
import os, re, asyncio, random, base64
from typing import Optional
from urllib.parse import quote_plus
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from playwright_stealth import stealth_async

app = FastAPI(title="Totalome Scraper v0.6", version="0.6")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MONEY_RE = re.compile(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)")
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

UA_ROTATION = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

def build_search_url(q: str, retailer: str) -> str:
    qenc = quote_plus(q)
    r = retailer.lower()
    if r == "homedepot":
        return f"https://www.homedepot.com/s/{qenc}"
    if r == "wayfair":
        return f"https://www.wayfair.com/keyword.php?keyword={qenc}"
    return f"https://duckduckgo.com/?q={qenc}"

async def consent_and_unhide(page):
    sels = [
        "#onetrust-accept-btn-handler",
        "button#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept all')",
        "button:has-text('Accept Cookies')",
        "button:has-text('Accept')",
    ]
    for s in sels:
        try:
            btn = await page.query_selector(s)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(0.2)
                break
        except: pass
    try:
        await page.evaluate("""
            const b = document.body; if (!b) return;
            b.style.visibility='visible'; b.style.opacity='1'; b.style.overflow='auto';
        """)
    except: pass

async def smart_scroll(page, steps=14, pause=250):
    for _ in range(steps):
        await page.mouse.wheel(0, 1400)
        await asyncio.sleep(pause/1000)

async def new_browser():
    pw = await async_playwright().start()
    ua = random.choice(UA_ROTATION)
    browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--disable-webgl","--disable-webgl2",
            "--disable-features=IsolateOrigins,site-per-process,WebGPU"
        ],
    )
    context = await browser.new_context(user_agent=ua, locale="en-US")
    page = await context.new_page()
    await stealth_async(page)
    return pw, browser, context, page

async def wait_for_grid(page, retailer: str):
    try:
        if retailer == "homedepot":
            await page.wait_for_selector('div[data-testid="product-pod"] >> nth=0', timeout=25000)
        elif retailer == "wayfair":
            # multiple fallbacks
            try:
                await page.wait_for_selector('div[data-enzyme-id*="plp-product"] >> nth=0', timeout=16000)
            except PWTimeout:
                try:
                    await page.wait_for_selector('a[data-enzyme-id*="ProductCard"] >> nth=0', timeout=16000)
                except PWTimeout:
                    await page.wait_for_selector('a[href*="/product/"] img >> nth=0', timeout=16000)
    except PWTimeout:
        pass

async def extract_homedepot(page):
    items = []
    cards = await page.query_selector_all('div[data-testid="product-pod"], div.product-pod--padding, div.pod-inner')
    for c in cards[:24]:
        # title candidates
        t = await c.query_selector('[data-automation="product-title"], [data-testid="product-title"], h3, h2, a[aria-label]')
        title = None
        if t:
            try: title = (await t.inner_text()).strip()
            except: 
                try: title = await t.get_attribute('aria-label')
                except: pass
        # link
        linknode = await c.query_selector('a[href]')
        url = None
        if linknode:
            url = await linknode.get_attribute('href')
            if url and url.startswith('/'):
                url = 'https://www.homedepot.com' + url
        # image
        image = None
        img = await c.query_selector('img[src]')
        if img: image = await img.get_attribute('src')
        # price by regex on card text
        text = None
        try: text = await c.inner_text()
        except: text = None
        price = money(text or '')
        if title or url:
            items.append({'title': title, 'price': price, 'image': image, 'url': url, 'retailer':'homedepot'})
    return items

async def extract_wayfair(page):
    items = []
    sel = 'a[data-enzyme-id*="ProductCard"], a:has(div[class*="ProductCard"]), a[href*="/product/"]'
    cards = await page.query_selector_all(sel)
    for a in cards[:24]:
        url = await a.get_attribute('href')
        if url and url.startswith('/'):
            url = 'https://www.wayfair.com' + url
        image = None
        img = await a.query_selector('img[src]')
        if img: image = await img.get_attribute('src')
        title = None
        t = await a.query_selector('p, span, h2, h3, [data-enzyme-id*="Title"], [data-enzyme-id*="name"]')
        if t:
            try: title = (await t.inner_text()).strip()
            except: pass
        text = None
        try: text = await a.inner_text()
        except: text = None
        price = money(text or '')
        if title or url:
            items.append({'title': title, 'price': price, 'image': image, 'url': url, 'retailer':'wayfair'})
    return items

@app.get('/')
def root():
    return {'message':'Totalome scraper v0.6 ready', 'docs':'/docs', 'health':'/health'}

@app.get('/health')
def health():
    return {'ok': True}

@app.get('/search')
async def search(q: str = Query(...), retailer: str = Query('homedepot'), debug: bool = False, shot: bool = False):
    retailer = retailer.lower()
    url = build_search_url(q, retailer)
    logs = []
    pw = browser = context = page = None
    try:
        pw, browser, context, page = await new_browser()
        page.on('console', lambda m: logs.append(m.text))
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await consent_and_unhide(page)
        await wait_for_grid(page, retailer)
        await smart_scroll(page, steps=16, pause=280)

        if retailer == 'homedepot':
            items = await extract_homedepot(page)
        elif retailer == 'wayfair':
            items = await extract_wayfair(page)
        else:
            items = []

        png = None
        if shot or debug:
            try: png = await page.screenshot(full_page=True)
            except: png = None

        # clean up
        await browser.close(); await pw.stop()

        if shot and not debug and png:
            return Response(content=png, media_type="image/png")

        if debug:
            data_url = 'data:image/png;base64,' + base64.b64encode(png).decode() if png else None
            return JSONResponse({
                'request': {'q': q, 'retailer': retailer, 'url': url},
                'page': {'title': await page.title() if page else None},
                'logs': logs[:15],
                'count': len(items),
                'sample': items[:5],
                'screenshot': data_url
            })

        return JSONResponse(items)
    except Exception as e:
        try:
            if browser: await browser.close()
            if pw: await pw.stop()
        except: pass
        return JSONResponse(status_code=500, content={'error': str(e), 'url': url, 'logs': logs[:10]})
