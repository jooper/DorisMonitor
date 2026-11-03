import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1600, "height": 900})
        await page.goto("http://localhost:5000", wait_until="networkidle")
        # Wait for login overlay to appear (401 → showLogin)
        await page.wait_for_timeout(2500)
        # Ensure login overlay visible; force show if not (in case already logged in via cookie)
        overlay_visible = await page.evaluate("document.getElementById('login-overlay').style.display")
        if overlay_visible != 'flex':
            await page.evaluate("showLogin()")
            await page.wait_for_timeout(1200)
        await page.screenshot(path="design-demos/current-login.png", full_page=False)
        # Also capture mouse interaction state (hover center)
        await page.mouse.move(800, 450)
        await page.wait_for_timeout(800)
        await page.screenshot(path="design-demos/current-login-hover.png", full_page=False)
        await browser.close()
        print("Screenshots saved: design-demos/current-login.png + current-login-hover.png")

asyncio.run(main())
