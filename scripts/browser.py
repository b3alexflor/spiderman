"""One shared headless Chromium for a whole ingest/report pass.

Launching a fresh browser per request (the old pattern) costs ~2s of pure local
overhead each time — over a 100-request pass that's minutes of nothing. Reusing
one browser changes NOTHING about politeness: the per-host request floors in
rate.py still gate every navigation; we just stop paying launch tax between them.

    session = BrowserSession()
    page = session.page()   # lazy-launches on first use
    ...
    page.close()            # per request
    session.reset()         # drop the context (fresh cookies) after a block
    session.close()         # end of pass
"""
from __future__ import annotations

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")


class BrowserSession:
    def __init__(self, user_agent: str = _UA):
        self.user_agent = user_agent
        self._pw = None
        self._browser = None
        self._ctx = None

    def page(self):
        """A new page in the shared context, launching the browser on first use."""
        if self._browser is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
        if self._ctx is None:
            self._ctx = self._browser.new_context(user_agent=self.user_agent,
                                                  locale="en-US")
        return self._ctx.new_page()

    def reset(self) -> None:
        """Drop the browsing context (cookies/cache) but keep the browser — used
        after an anti-bot block so the next request starts from a clean slate."""
        if self._ctx is not None:
            try:
                self._ctx.close()
            except Exception:
                pass
            self._ctx = None

    def close(self) -> None:
        self.reset()
        for attr in ("_browser", "_pw"):
            obj = getattr(self, attr)
            if obj is not None:
                try:
                    obj.close() if attr == "_browser" else obj.stop()
                except Exception:
                    pass
                setattr(self, attr, None)
