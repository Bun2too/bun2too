import assert from "node:assert/strict";
import { test } from "node:test";
import { act, createElement } from "react";
import CookieConsentProvider, {
  CookieSettingsButton,
  useCookieConsent,
} from "../src/components/CookieConsent";
import {
  COOKIE_CONSENT_NAME,
  COOKIE_CONSENT_SECONDS,
  READING_STORAGE_KEY,
  cookieConsentFromHeader,
  createCookieConsent,
} from "../src/lib/cookie-consent";
import { componentDom, button, click } from "./helpers/component-dom";

function Probe() {
  const { preferencesAllowed } = useCookieConsent();
  return createElement(
    "output",
    { "data-preferences": preferencesAllowed },
    String(preferencesAllowed),
  );
}
function controls() {
  return createElement(
    CookieConsentProvider,
    null,
    createElement(Probe),
    createElement(CookieSettingsButton),
  );
}
function writeCookie(value: unknown) {
  document.cookie = `${COOKIE_CONSENT_NAME}=${encodeURIComponent(JSON.stringify(value))}; Path=/`;
}

test("cookie choices start denied, require explicit selection, and withdrawal clears only reading state", async (t) => {
  const dom = componentDom(t);
  dom.window.localStorage.setItem(READING_STORAGE_KEY, '["old-article"]');
  dom.window.localStorage.setItem("unrelated-fixture", "preserve");
  const { container } = await dom.mount(controls());
  assert.equal(container.querySelector("output")!.textContent, "false");
  assert.equal(localStorage.getItem(READING_STORAGE_KEY), null);
  const banner = container.querySelector(".cookie-banner")!;
  await click(button(banner, /Customize/));
  const dialog = container.querySelector("dialog")!;
  assert.equal(dialog.open, true);
  assert.equal(
    dialog.querySelectorAll('input[type="checkbox"]:checked').length,
    1,
  );
  await click(
    dialog.querySelector('[aria-labelledby="cookie-preferences-label"]')!,
  );
  await click(button(dialog, /Save choices/));
  assert.equal(dialog.open, false);
  assert.equal(container.querySelector(".cookie-banner"), null);
  assert.equal(container.querySelector("output")!.textContent, "true");
  const record = cookieConsentFromHeader(document.cookie)!;
  assert.equal(record.preferences, true);
  assert.equal(record.analytics, false);
  assert.equal(record.marketing, false);
  localStorage.setItem(READING_STORAGE_KEY, '["read-article"]');
  await click(button(container, /^Cookie settings$/));
  await click(button(dialog, /^Necessary only$/));
  assert.equal(container.querySelector("output")!.textContent, "false");
  assert.equal(localStorage.getItem(READING_STORAGE_KEY), null);
  assert.equal(localStorage.getItem("unrelated-fixture"), "preserve");
  assert.equal(cookieConsentFromHeader(document.cookie)!.analytics, false);
});

test("closing or canceling customization does not grant consent; accepting optional sets each category", async (t) => {
  const dom = componentDom(t);
  const { container } = await dom.mount(controls());
  await click(button(container.querySelector(".cookie-banner")!, /Customize/));
  const dialog = container.querySelector("dialog")!;
  await click(
    dialog.querySelector('[aria-labelledby="cookie-analytics-label"]')!,
  );
  await click(
    dialog.querySelector('[aria-labelledby="cookie-marketing-label"]')!,
  );
  await act(async () =>
    dialog.dispatchEvent(new Event("cancel", { cancelable: true })),
  );
  assert.equal(dialog.open, false);
  assert.equal(cookieConsentFromHeader(document.cookie), null);
  await click(button(container.querySelector(".cookie-banner")!, /Customize/));
  assert.equal(
    dialog.querySelector<HTMLInputElement>(
      '[aria-labelledby="cookie-analytics-label"]',
    )!.checked,
    false,
  );
  await click(dialog.querySelector('[aria-label="Close cookie settings"]')!);
  assert.equal(cookieConsentFromHeader(document.cookie), null);
  await click(
    button(container.querySelector(".cookie-banner")!, /Accept optional/),
  );
  const record = cookieConsentFromHeader(document.cookie)!;
  assert.ok(record.preferences && record.analytics && record.marketing);
  await click(button(container, /^Cookie settings$/));
  assert.equal(
    dialog.querySelectorAll('input[type="checkbox"]:checked').length,
    4,
  );
  await act(async () => dialog.close());
  assert.equal(dialog.open, false);
});

test("focus and visibility refresh another tab's choices without extending their expiry", async (t) => {
  const dom = componentDom(t);
  const initial = createCookieConsent({
    preferences: true,
    analytics: false,
    marketing: false,
  });
  writeCookie(initial);
  localStorage.setItem(READING_STORAGE_KEY, '["fixture-read"]');
  const { container } = await dom.mount(controls());
  assert.equal(container.querySelector(".cookie-banner"), null);
  assert.equal(localStorage.getItem(READING_STORAGE_KEY), '["fixture-read"]');
  writeCookie(
    createCookieConsent({
      preferences: false,
      analytics: false,
      marketing: false,
    }),
  );
  await act(async () => dom.window.dispatchEvent(new Event("focus")));
  assert.equal(container.querySelector("output")!.textContent, "false");
  assert.equal(localStorage.getItem(READING_STORAGE_KEY), null);
  writeCookie(initial);
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "hidden",
  });
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  assert.equal(container.querySelector("output")!.textContent, "false");
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  });
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  assert.equal(container.querySelector("output")!.textContent, "true");
  assert.equal(
    cookieConsentFromHeader(document.cookie)!.expiresAt,
    initial.expiresAt,
  );
});

test("expiry callback withdraws stale permission and removes persisted reading state", async (t) => {
  const dom = componentDom(t);
  const record = createCookieConsent(
    { preferences: true, analytics: false, marketing: false },
    Date.now() - COOKIE_CONSENT_SECONDS * 1000 + 10000,
  );
  writeCookie(record);
  let expire: () => void;
  const nativeSetTimeout = dom.window.setTimeout.bind(dom.window);
  t.mock.method(
    dom.window,
    "setTimeout",
    (callback: () => void, delay: number) => {
      if (delay >= 1000) {
        assert.ok(delay <= 10000);
        expire = callback;
        return 42;
      }
      return nativeSetTimeout(callback, delay);
    },
  );
  const cancel = t.mock.method(dom.window, "clearTimeout");
  const mounted = await dom.mount(controls());
  localStorage.setItem(READING_STORAGE_KEY, '["fixture-read"]');
  document.cookie = `${COOKIE_CONSENT_NAME}=; Path=/; Max-Age=0`;
  await act(async () => expire());
  assert.equal(mounted.container.querySelector("output")!.textContent, "false");
  assert.ok(mounted.container.querySelector(".cookie-banner"));
  assert.equal(localStorage.getItem(READING_STORAGE_KEY), null);
  assert.ok(cancel.mock.calls.some((call) => call.arguments[0] === 42));
});

test("blocked cookie and storage access keeps public content usable and reports memory-only choices", async (t) => {
  const dom = componentDom(t);
  Object.defineProperty(document, "cookie", {
    configurable: true,
    get() {
      throw new Error("cookie access blocked");
    },
    set() {
      throw new Error("cookie persistence blocked");
    },
  });
  t.mock.method(dom.window.Storage.prototype, "removeItem", () => {
    throw new Error("storage blocked");
  });
  const { container } = await dom.mount(controls());
  assert.equal(container.querySelector("output")!.textContent, "false");
  await click(
    button(container.querySelector(".cookie-banner")!, /Accept optional/),
  );
  assert.equal(container.querySelector("output")!.textContent, "true");
  assert.match(
    container.querySelector('[role="status"]')!.textContent!,
    /could not remember/,
  );
  await click(button(container, /^Cookie settings$/));
  await click(button(container.querySelector("dialog")!, /^Necessary only$/));
  assert.equal(container.querySelector("output")!.textContent, "false");
});
