import assert from "node:assert/strict";
import { test } from "node:test";
import { AsyncLocalStorage } from "node:async_hooks";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  componentDom,
  button,
  click,
  json,
  publicEnv,
} from "./helpers/component-dom";
import type { Insight } from "../src/lib/insights";

Object.defineProperty(globalThis, "AsyncLocalStorage", {
  configurable: true,
  value: AsyncLocalStorage,
});

const previews = [
  {
    id: "first-story",
    title: "First fixture story",
    published_at: "2026-11-18T00:00:00Z",
  },
  {
    id: "second-story",
    title: "Second fixture story",
    published_at: "2026-11-19T00:00:00Z",
  },
];
function article(id: string, title: string, image: string | null): Insight {
  return {
    id,
    title,
    body: "A fixture body for a public article.",
    summary: "Fixture summary.",
    published_at: "2026-11-18T12:00:00Z",
    url: `https://editorial.example.test/insights/${id}`,
    image_url: image,
    image_alt: "Fixture artwork",
    reading_minutes: 4,
    source_urls: [],
  };
}

test("reading list stays view-only without preference consent and marks articles read", async (t) => {
  const dom = componentDom(t);
  dom.window.localStorage.setItem("bun2too-read-insights", '["first-story"]');
  const { default: InsightUpdates } =
    await import("../src/components/InsightUpdates");
  const mounted = await dom.mount(
    createElement(InsightUpdates, { articles: previews }),
  );
  assert.equal(
    mounted.container.querySelector(".insights-count")!.textContent,
    "2",
  );
  await click(button(mounted.container, /Your reading list/));
  assert.match(
    mounted.container.textContent!,
    /unless you enable optional preferences/,
  );
  await click(button(mounted.container, /Mark all as read/));
  assert.equal(
    mounted.container.querySelector(".insights-count")!.textContent,
    "0",
  );
  assert.equal(
    dom.window.localStorage.getItem("bun2too-read-insights"),
    '["first-story"]',
  );
  assert.match(
    mounted.container.querySelector('[role="status"]')!.textContent!,
    /this view/,
  );
});

test("push setup requests consent, registers only on demand and rolls back failed persistence", async (t) => {
  const dom = componentDom(t);
  const unsubscribed: boolean[] = [];
  const subscribedOptions: unknown[] = [];
  const subscription = {
    toJSON: () => ({ endpoint: "https://push.example.test/fixture" }),
    unsubscribe: async () => {
      unsubscribed.push(true);
      return true;
    },
  };
  const registration = {
    pushManager: {
      getSubscription: async () => null,
      subscribe: async (options: unknown) => {
        subscribedOptions.push(options);
        return subscription;
      },
    },
  };
  Object.defineProperty(dom.window.navigator, "serviceWorker", {
    configurable: true,
    value: {
      getRegistration: async () => undefined,
      register: async (path: string, options: unknown) => {
        assert.equal(path, "/insights-sw.js");
        assert.deepEqual(options, { scope: "/" });
        return registration;
      },
      ready: Promise.resolve(registration),
    },
  });
  Object.defineProperty(dom.window, "PushManager", {
    configurable: true,
    value: class PushManager {},
  });
  const priorNotification = Object.getOwnPropertyDescriptor(
    globalThis,
    "Notification",
  );
  class FixtureNotification {
    static requestPermission = t.mock.fn(
      async () => "granted" as NotificationPermission,
    );
  }
  Object.defineProperty(globalThis, "Notification", {
    configurable: true,
    value: FixtureNotification,
  });
  Object.defineProperty(dom.window, "Notification", {
    configurable: true,
    value: FixtureNotification,
  });
  t.after(() => {
    if (priorNotification)
      Object.defineProperty(globalThis, "Notification", priorNotification);
    else Reflect.deleteProperty(globalThis, "Notification");
  });
  let calls = 0;
  t.mock.method(globalThis, "fetch", async (url) => {
    calls++;
    if (url === "/api/insights/push-config")
      return json({ public_key: "AQID" });
    assert.equal(url, "/api/insights/push-subscriptions");
    return json({ error: "storage fixture failed" }, 503);
  });
  const { default: InsightUpdates } =
    await import("../src/components/InsightUpdates");
  const mounted = await dom.mount(
    createElement(InsightUpdates, { articles: previews }),
  );
  assert.equal(calls, 0);
  await click(button(mounted.container, /browser notifications/));
  assert.equal(calls, 2);
  assert.deepEqual(
    JSON.parse(
      (
        globalThis.fetch as unknown as {
          mock: { calls: { arguments: [string, RequestInit?] }[] };
        }
      ).mock.calls.at(-1)!.arguments[1]!.body as string,
    ),
    {
      subscription: { endpoint: "https://push.example.test/fixture" },
      consent: true,
    },
  );
  assert.equal(
    (subscribedOptions[0] as { applicationServerKey: Uint8Array })
      .applicationServerKey.length,
    3,
  );
  assert.deepEqual(unsubscribed, [true]);
  assert.match(
    mounted.container.querySelector('[role="status"]')!.textContent!,
    /Could not save notification preferences/,
  );
});

test("push config errors and existing subscription opt-out avoid duplicate registration", async (t) => {
  const dom = componentDom(t);
  let registered = 0;
  let removed = 0;
  const registration = {
    pushManager: {
      getSubscription: async () => ({
        unsubscribe: async () => {
          removed++;
        },
      }),
    },
  };
  Object.defineProperty(dom.window.navigator, "serviceWorker", {
    configurable: true,
    value: {
      getRegistration: async () => registration,
      register: async () => {
        registered++;
        return registration;
      },
      ready: Promise.resolve(registration),
    },
  });
  Object.defineProperty(dom.window, "PushManager", {
    configurable: true,
    value: class PushManager {},
  });
  Object.defineProperty(dom.window, "Notification", {
    configurable: true,
    value: class Notification {},
  });
  const oldNotification = Object.getOwnPropertyDescriptor(
    globalThis,
    "Notification",
  );
  Object.defineProperty(globalThis, "Notification", {
    configurable: true,
    value: dom.window.Notification,
  });
  t.after(() => {
    if (oldNotification)
      Object.defineProperty(globalThis, "Notification", oldNotification);
    else Reflect.deleteProperty(globalThis, "Notification");
  });
  const { default: InsightUpdates } =
    await import("../src/components/InsightUpdates");
  const mounted = await dom.mount(
    createElement(InsightUpdates, { articles: previews }),
  );
  await click(button(mounted.container, /browser notifications/));
  assert.equal(removed, 1);
  assert.equal(registered, 1);
  assert.equal(
    mounted.container.querySelector('[role="status"]')!.textContent,
    "Browser push notifications are off.",
  );
});

test("insights feed renders featured and placeholder articles", async (t) => {
  const { default: InsightsFeed } =
    await import("../src/components/InsightsFeed");
  publicEnv(t, { INSIGHTS_API_ORIGIN: "https://editorial.example.test" });
  const payload = {
    articles: [
      article(
        "first-story",
        "First story",
        "https://images.example.test/first.jpg",
      ),
      article("second-story", "Second story", null),
      article(
        "third-story",
        "Third story",
        "https://images.example.test/third.jpg",
      ),
    ],
  };
  t.mock.method(globalThis, "fetch", async (url) => {
    assert.equal(url, "https://editorial.example.test/insights/api/articles");
    return json(payload);
  });
  const work = { route: "/insights", forceStatic: true };
  const { workAsyncStorage } =
    await import("next/dist/server/app-render/work-async-storage.external.js");
  const element = await workAsyncStorage.run(work as never, () =>
    InsightsFeed(),
  );
  const html = renderToStaticMarkup(element);
  assert.match(html, /data-insights-state="ready"/);
  assert.match(html, /LATEST PERSPECTIVE/);
  assert.match(html, /FIELD NOTE/);
  assert.match(html, /loading="eager"/);
  assert.match(html, /loading="lazy"/);
  assert.match(html, /Ideas\./);
  assert.match(html, /First story/);
  assert.match(html, /href="\/insights\/second-story"/);
});

test("insights feed reports empty and unavailable states", async (t) => {
  const { default: InsightsFeed } =
    await import("../src/components/InsightsFeed");
  publicEnv(t, { INSIGHTS_API_ORIGIN: "https://editorial.example.test" });
  t.mock.method(globalThis, "fetch", async () => json({ articles: [] }));
  const { workAsyncStorage } =
    await import("next/dist/server/app-render/work-async-storage.external.js");
  const work = { route: "/insights", forceStatic: true };
  const empty = await workAsyncStorage.run(work as never, () => InsightsFeed());
  assert.match(renderToStaticMarkup(empty), /data-insights-state="empty"/);
  t.mock.restoreAll();
  t.mock.method(globalThis, "fetch", async () => {
    throw new TypeError("private fixture transport");
  });
  const unavailable = await workAsyncStorage.run(work as never, () =>
    InsightsFeed(),
  );
  assert.match(
    renderToStaticMarkup(unavailable),
    /data-insights-state="unavailable"/,
  );
});
