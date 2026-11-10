"""Run against python -m tests.preview_server. Records a labeled fixture walkthrough."""
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright

OUT = Path('artifacts/browser')
OUT.mkdir(parents=True, exist_ok=True)
Image.new('RGB', (600, 400), '#8b6948').save(OUT / 'test-grounds.jpg')


if __name__ == '__main__':
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        public_context = browser.new_context(viewport={'width': 390, 'height': 844})
        driver_context = browser.new_context(viewport={'width': 390, 'height': 844})
        user_context = browser.new_context(viewport={'width': 390, 'height': 844})
        page = public_context.new_page()
        driver = driver_context.new_page()
        user = user_context.new_page()
        errors = []
        for item in (page, driver, user):
            item.on('pageerror', lambda error: errors.append(str(error)))

        page.goto('http://127.0.0.1:5055/')
        page.screenshot(path=str(OUT / 'mobile-home.png'), full_page=True)

        driver.goto('http://127.0.0.1:5055/staff/login')
        driver.get_by_label('Username', exact=True).fill('driver')
        driver.get_by_label('Password', exact=True).fill('test-password-123')
        driver.get_by_role('button', name='Sign in').click()
        driver.goto('http://127.0.0.1:5055/hubs/1/access')
        driver.get_by_role('button', name='Open lid').click()
        driver.get_by_label('Rider or source').fill('Demo rider')
        driver.get_by_label('Weight added').fill('5')
        driver.locator('#photo').set_input_files(str(OUT / 'test-grounds.jpg'))
        driver.screenshot(path=str(OUT / 'mobile-driver-open.png'), full_page=True)
        driver.get_by_role('button', name='Record drop-off').click()
        driver.get_by_text('5 kg added').wait_for()
        page.get_by_text('5 kg just added', exact=False).wait_for(timeout=20000)
        assert page.locator('#total-weight').inner_text() == '5'

        user.goto('http://127.0.0.1:5055/account/register')
        user.get_by_label('Account type').select_option('individual')
        user.get_by_label('Contact name').fill('Community User')
        user.get_by_label('Phone number').fill('+65 8123 4567')
        user.get_by_label('Email').fill('user@example.com')
        user.get_by_label('Password', exact=True).fill('community-pass-123')
        user.get_by_label('Repeat password').fill('community-pass-123')
        user.get_by_role('checkbox').check()
        user.get_by_role('button', name='Create account').click()
        user.get_by_label('Email').fill('user@example.com')
        user.get_by_label('Password').fill('community-pass-123')
        user.get_by_role('button', name='Sign in').click()
        user.goto('http://127.0.0.1:5055/hubs/1/access')
        user.get_by_role('button', name='Open lid').click()
        user.get_by_label('New weight after taking grounds').fill('2')
        user.locator('#photo').set_input_files(str(OUT / 'test-grounds.jpg'))
        user.get_by_text('3 kg will be recorded as collected.').wait_for()
        user.screenshot(path=str(OUT / 'mobile-collection-open.png'), full_page=True)
        user.get_by_role('button', name='Confirm collection').click()
        user.get_by_text('3 kg collected').wait_for()
        expect(page.locator('#total-weight')).to_have_text('2', timeout=20000)

        for width in [360, 390, 768, 1280]:
            page.set_viewport_size({'width': width, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow at {width}px'
        page.screenshot(path=str(OUT / 'desktop-home.png'), full_page=True)
        assert not errors, errors
        public_context.close()
        driver_context.close()
        user_context.close()
        browser.close()
        print('Browser fixture registration, lid simulation, drop-off, collection, and responsive checks passed.')
