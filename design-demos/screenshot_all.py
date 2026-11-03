import asyncio, json
from playwright.async_api import async_playwright

async def main():
    cfg = json.load(open("config.json", encoding="utf-8"))
    auth = cfg.get("auth", {})
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1600, "height": 900})
        page = await ctx.new_page()
        await page.goto("http://localhost:5000", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        # Login first
        await page.fill("#login-username", auth.get("username", "admin"))
        await page.fill("#login-password", auth.get("password", ""))
        await page.click("#login-btn")
        await page.wait_for_timeout(3000)
        tabs = ["cluster", "mv", "graph", "jobs", "tables", "catalog", "config"]
        for tab in tabs:
            sel = f".nav-item[data-tab='{tab}']"
            await page.click(sel)
            await page.wait_for_timeout(2000)
            await page.screenshot(path=f"design-demos/current-{tab}.png")
            print(f"captured: {tab}")
        await browser.close()
        print("done")

asyncio.run(main())
