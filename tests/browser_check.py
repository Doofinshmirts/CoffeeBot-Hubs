"""Run against python -m tests.preview_server. Records a labeled fixture walkthrough."""
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image

OUT = Path('artifacts/browser')
OUT.mkdir(parents=True, exist_ok=True)
Image.new('RGB',(600,400),'#8b6948').save(OUT/'test-grounds.jpg')

if __name__ == '__main__':
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        community = browser.new_context(viewport={'width':390,'height':844}, record_video_dir=str(OUT/'fixture-video'))
        driver = browser.new_context(viewport={'width':390,'height':844})
        page = community.new_page(); staff = driver.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:5055/')
        page.screenshot(path=str(OUT/'mobile-home.png'),full_page=True)
        staff.goto('http://127.0.0.1:5055/staff/login')
        staff.get_by_label('Username',exact=True).fill('driver')
        staff.get_by_label('Password',exact=True).fill('test-password-123')
        staff.get_by_role('button',name='Sign in').click()
        staff.locator('#hub_id').select_option('1')
        staff.locator('#rider_source').fill('Demo rider')
        staff.locator('#weight_kg').fill('5')
        staff.locator('#photo').set_input_files(str(OUT/'test-grounds.jpg'))
        staff.screenshot(path=str(OUT/'mobile-dropoff.png'),full_page=True)
        staff.get_by_role('button',name='Record drop-off').click()
        staff.get_by_text('Your 5 kg drop-off is saved.').wait_for()
        page.get_by_text('5 kg just added',exact=False).wait_for(timeout=20000)
        assert page.locator('#total-weight').inner_text() == '5'
        page.screenshot(path=str(OUT/'mobile-alert.png'),full_page=True)
        for width in [360,390,768,1280]:
            page.set_viewport_size({'width':width,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow at {width}px'
        page.screenshot(path=str(OUT/'desktop-home.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        staff.goto('http://127.0.0.1:5055/staff/batches')
        staff.on('dialog',lambda dialog:dialog.accept())
        staff.get_by_role('button',name='Mark entire batch collected').click()
        page.wait_for_function("document.querySelector('#total-weight').textContent === '0'",timeout=20000)
        community.set_offline(True)
        page.get_by_text('Reconnecting…',exact=False).wait_for(timeout=20000)
        community.set_offline(False)
        page.get_by_text('Up to date',exact=False).wait_for(timeout=20000)
        assert not errors, errors
        community.close(); driver.close(); browser.close()
        print('Browser fixture workflow, alerts, collection, reconnect and mobile overflow checks passed.')
