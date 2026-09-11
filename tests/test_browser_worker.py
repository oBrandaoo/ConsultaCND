import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from browser_worker import BrowserError,browser_mode,close_browser,env_bool,launch_federal_browser,launch_municipal_browser


class FakeContext:
    def __init__(self):
        self.closed=False
    async def close(self):
        self.closed=True


class FakeChromium:
    def __init__(self):
        self.persistent=None
        self.launch_options=None
        self.context=FakeContext()
    async def launch_persistent_context(self,path,**options):
        self.persistent=(path,options)
        return self.context
    async def launch(self,**options):
        self.launch_options=options
        return object()


class FakePlaywright:
    def __init__(self):
        self.chromium=FakeChromium()


class ConfigurationTest(unittest.IsolatedAsyncioTestCase):
    def test_modes_and_boolean_validation(self):
        with patch.dict('os.environ',{'CERTIFICA_BROWSER_MODE':'server'},clear=False):
            self.assertEqual(browser_mode(),'server')
        with patch.dict('os.environ',{'CERTIFICA_BROWSER_MODE':'invalid'},clear=False):
            with self.assertRaises(BrowserError):browser_mode()
        with patch.dict('os.environ',{'FLAG':'yes'},clear=False):self.assertTrue(env_bool('FLAG'))
        with patch.dict('os.environ',{'FLAG':'invalid'},clear=False):
            with self.assertRaises(BrowserError):env_bool('FLAG')

    async def test_server_federal_uses_persistent_full_chromium(self):
        playwright=FakePlaywright()
        with tempfile.TemporaryDirectory() as directory:
            values={'CERTIFICA_BROWSER_MODE':'server','CERTIFICA_HEADLESS':'false','CERTIFICA_PROFILE_DIR':directory}
            with patch.dict('os.environ',values,clear=False):
                browser,process,profile=await launch_federal_browser(playwright)
            path,options=playwright.chromium.persistent
            self.assertEqual(Path(path),Path(directory))
            self.assertFalse(options['headless'])
            if os.name == 'nt':
                self.assertIn('--window-position=-32000,-32000',options['args'])
            self.assertIsNone(process);self.assertIsNone(profile)
            await close_browser(browser)
            self.assertTrue(playwright.chromium.context.closed)

    async def test_server_municipal_uses_bundled_full_chromium(self):
        playwright=FakePlaywright()
        values={'CERTIFICA_BROWSER_MODE':'server','CERTIFICA_HEADLESS':'false'}
        with patch.dict('os.environ',values,clear=False):
            await launch_municipal_browser(playwright)
        self.assertFalse(playwright.chromium.launch_options['headless'])
        if os.name == 'nt':
            self.assertIn('--window-position=-32000,-32000',playwright.chromium.launch_options['args'])


if __name__=='__main__':unittest.main()
