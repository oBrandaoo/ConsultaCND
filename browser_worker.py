"""Navegador do worker: Edge local no Windows ou Chromium no servidor."""
import asyncio
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


class BrowserError(Exception):
    status = 'indisponivel'


class PersistentBrowser:
    def __init__(self, context):
        self.context = context
        self.contexts = [context]

    async def close(self):
        await self.context.close()


def browser_mode():
    mode = os.environ.get('CERTIFICA_BROWSER_MODE', '').strip().lower()
    if not mode:
        return 'local-edge' if os.name == 'nt' else 'server'
    if mode not in ('local-edge', 'server'):
        raise BrowserError('CERTIFICA_BROWSER_MODE deve ser local-edge ou server.')
    return mode


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    if value.strip().lower() in ('1', 'true', 'yes', 'on'):
        return True
    if value.strip().lower() in ('0', 'false', 'no', 'off'):
        return False
    raise BrowserError(f'{name} deve ser true ou false.')


def find_edge():
    candidates = []
    for variable in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA'):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / 'Microsoft/Edge/Application/msedge.exe')
    edge = next((path for path in candidates if path.is_file()), None)
    if not edge:
        raise BrowserError('Microsoft Edge não encontrado. Instale o navegador ou use o modo server.')
    return edge


async def launch_server_browser(playwright):
    """Executa Chromium no host; com Xvfb, headless=False não abre janela para o usuário."""
    profile = Path(os.environ.get('CERTIFICA_PROFILE_DIR', str(ROOT / '.runtime/server-browser-profile')))
    profile.mkdir(parents=True, exist_ok=True)
    headless = env_bool('CERTIFICA_HEADLESS', False)
    arguments = ['--no-sandbox', '--no-first-run', '--no-default-browser-check', '--disable-dev-shm-usage']
    # A prévia sem Docker roda no Windows. O Chromium completo fica fora da área
    # visível, reproduzindo o navegador headed que o Xvfb hospeda no contêiner.
    if os.name == 'nt' and not headless:
        arguments.extend(['--window-position=-32000,-32000', '--window-size=1365,900'])
    try:
        context = await playwright.chromium.launch_persistent_context(
            str(profile),
            headless=headless,
            locale='pt-BR',
            viewport={'width': 1365, 'height': 900},
            args=arguments,
        )
        return PersistentBrowser(context), None, None
    except Exception as error:
        raise BrowserError(f'Não foi possível iniciar o Chromium do servidor ({type(error).__name__}).')


async def launch_local_edge(playwright):
    external = os.environ.get('CERTIFICA_EDGE_CDP')
    if external:
        parsed = urlsplit(external)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or not parsed.port:
            raise BrowserError('A configuração local do Edge é inválida.')
        browser = await playwright.chromium.connect_over_cdp(external, timeout=10000)
        return browser, None, None

    runtime = ROOT / '.runtime'
    runtime.mkdir(exist_ok=True)
    profile = tempfile.TemporaryDirectory(prefix='federal-edge-', dir=runtime)
    port_file = Path(profile.name) / 'DevToolsActivePort'
    arguments = [
        str(find_edge()), '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
        f'--user-data-dir={profile.name}', '--no-first-run', '--disable-sync',
        '--disable-features=msEdgeFirstRunExperience,msEdgeSync', '--no-default-browser-check',
        '--new-window', 'about:blank',
    ]
    try:
        process = subprocess.Popen(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 25
        last_error = None
        while time.monotonic() < deadline:
            try:
                port = int(port_file.read_text(encoding='utf-8').splitlines()[0])
                endpoint = f'http://127.0.0.1:{port}'
                await asyncio.to_thread(lambda: urllib.request.urlopen(endpoint + '/json/version', timeout=.5).close())
                browser = await playwright.chromium.connect_over_cdp(endpoint, timeout=10000)
                return browser, process, profile
            except Exception as error:
                last_error = error
                await asyncio.sleep(.2)
        detail = type(last_error).__name__ if last_error else 'sem resposta'
        raise BrowserError(f'Não foi possível conectar à janela temporária do Edge ({detail}).')
    except Exception as direct_error:
        if 'process' in locals() and process.poll() is None:
            process.terminate()
        try:
            profile.cleanup()
        except OSError:
            pass
        fallback = tempfile.TemporaryDirectory(prefix='federal-playwright-', dir=runtime)
        try:
            context = await playwright.chromium.launch_persistent_context(
                fallback.name, channel='msedge', headless=False, locale='pt-BR',
                args=['--no-first-run', '--no-default-browser-check'])
            return PersistentBrowser(context), None, fallback
        except Exception as fallback_error:
            try:
                fallback.cleanup()
            except OSError:
                pass
            raise BrowserError(
                f'Não foi possível abrir o Edge ({type(direct_error).__name__} / {type(fallback_error).__name__}).')


async def launch_federal_browser(playwright):
    if browser_mode() == 'server':
        return await launch_server_browser(playwright)
    return await launch_local_edge(playwright)


async def launch_municipal_browser(playwright):
    if browser_mode() == 'server':
        headless = env_bool('CERTIFICA_HEADLESS', False)
        arguments = []
        if os.name == 'nt' and not headless:
            arguments.extend([
                '--window-position=-32000,-32000',
                '--window-size=1365,900',
            ])
        return await playwright.chromium.launch(headless=headless, args=arguments)
    return await playwright.chromium.launch(channel='msedge', headless=True)


async def close_browser(browser, process=None, profile=None):
    try:
        await browser.close()
    finally:
        try:
            if process and process.poll() is None:
                process.terminate()
                await asyncio.to_thread(process.wait, 5)
        except Exception:
            if process and process.poll() is None:
                process.kill()
        try:
            if profile:
                profile.cleanup()
        except OSError:
            pass
