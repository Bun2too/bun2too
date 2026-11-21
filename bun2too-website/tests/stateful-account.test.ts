import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { Auth0Context, initialContext } from "@auth0/auth0-react";
import type { User } from "@auth0/auth0-react";
import {
  componentDom,
  button,
  click,
  json,
  publicEnv,
  submit,
  flush,
} from "./helpers/component-dom";

function account(value: Record<string, unknown>) {
  return createElement(
    Auth0Context.Provider,
    { value: { ...initialContext, ...value } as never },
    createElement("div", null, createElement(requireAccount())),
  );
}
function requireAccount() {
  // The import follows the public configuration fixture in each test.
  return AccountModule;
}
let AccountModule: typeof import("../src/components/Account").default;
async function loadAccount(
  t: Parameters<typeof componentDom>[0],
  audience = "https://api.example.test",
) {
  publicEnv(t, {
    NEXT_PUBLIC_AUTH0_DOMAIN: "tenant.example.test",
    NEXT_PUBLIC_AUTH0_CLIENT_ID: "fixture-client-id",
    NEXT_PUBLIC_AUTH0_AUDIENCE: audience,
    NEXT_PUBLIC_AUTH0_EMAIL_CONNECTION: "email-fixture",
  });
  AccountModule = (await import("../src/components/Account")).default;
}

const verifiedUser: User = {
  name: "Fixture User",
  email: "person@example.test",
  email_verified: true,
};
const preference = { status: "subscribed", topics: ["ai-automation"] };

test("account loading, login methods and safe sign-in errors", async (t) => {
  const dom = componentDom(t);
  await loadAccount(t);
  const mounted = await dom.mount(
    account({ isLoading: true, isAuthenticated: false }),
  );
  assert.match(
    mounted.container.querySelector('[role="status"]')!.textContent!,
    /Loading your account/,
  );
  await mounted.render(
    account({
      isLoading: false,
      isAuthenticated: false,
      error: new Error("callback fixture"),
    }),
  );
  assert.match(
    mounted.container.querySelector('[role="alert"]')!.textContent!,
    /Sign-in could not complete/,
  );
  assert.ok(button(mounted.container, /^Log in/));
  assert.ok(button(mounted.container, /^Create an account/));
  assert.ok(button(mounted.container, /^Continue with email/));
});

test("account loads preferences, enforces verified consent and submits topic changes", async (t) => {
  const dom = componentDom(t);
  await loadAccount(t);
  const calls: { url: string; options: RequestInit }[] = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    return options.method === "PATCH"
      ? json({ newsletter: { status: "subscribed", topics: ["fintech"] } })
      : json({ newsletter: preference });
  });
  const token = t.mock.fn(async () => "fixture-access-token");
  const mounted = await dom.mount(
    account({
      isLoading: false,
      isAuthenticated: true,
      user: verifiedUser,
      getAccessTokenSilently: token,
    }),
  );
  await flush();
  assert.match(mounted.container.textContent!, /Subscribed/);
  assert.equal(calls[0].url, "/api/preferences");
  assert.equal(calls[0].options.method, "GET");
  assert.equal(
    (calls[0].options.headers as Record<string, string>).Authorization,
    "Bearer fixture-access-token",
  );
  assert.deepEqual(token.mock.calls[0].arguments[0].authorizationParams, {
    audience: "https://api.example.test",
    scope: "openid profile email manage:subscriptions",
  });
  const confirm = button(mounted.container, /Confirm subscription & topics/);
  assert.equal(confirm.disabled, true);
  await click(
    mounted.container.querySelector('input[type="checkbox"][required]')!,
  );
  assert.equal(confirm.disabled, false);
  await submit(mounted.container.querySelector("form")!);
  assert.equal(calls[1].options.method, "PATCH");
  assert.deepEqual(JSON.parse(calls[1].options.body as string), {
    subscribed: true,
    topics: ["ai-automation"],
    consent: true,
  });
  assert.match(
    mounted.container.querySelector('[role="status"]')!.textContent!,
    /subscription is confirmed/,
  );
});

test("unverified users cannot confirm; unsubscribe and preference recovery stay available", async (t) => {
  const dom = componentDom(t);
  await loadAccount(t);
  const calls: RequestInit[] = [];
  t.mock.method(globalThis, "fetch", async (_url, options) => {
    calls.push(options);
    return options.method === "PATCH"
      ? json({ newsletter: null })
      : json({
          newsletter: {
            status: "pending_verification",
            topics: ["customer-technology"],
          },
        });
  });
  const login = t.mock.fn(async () => {});
  const mounted = await dom.mount(
    account({
      isLoading: false,
      isAuthenticated: true,
      user: { ...verifiedUser, email_verified: false },
      getAccessTokenSilently: async () => "fixture",
      loginWithRedirect: login,
    }),
  );
  await flush();
  assert.match(mounted.container.textContent!, /EMAIL NOT YET VERIFIED/);
  await click(
    mounted.container.querySelector('input[type="checkbox"][required]')!,
  );
  assert.equal(
    button(mounted.container, /Confirm subscription/).disabled,
    true,
  );
  await click(button(mounted.container, /^Unsubscribe$/));
  assert.deepEqual(JSON.parse(calls[1].body as string), {
    subscribed: false,
    topics: ["customer-technology"],
    consent: true,
  });
  assert.match(
    mounted.container.querySelector('[role="status"]')!.textContent!,
    /You are unsubscribed/,
  );
  assert.deepEqual(calls[1].method, "PATCH");
});

test("preference token and HTTP errors provide recovery without exposing provider details", async (t) => {
  const dom = componentDom(t);
  await loadAccount(t);
  const tokenFailure = t.mock.fn(async () => {
    throw new Error("private token endpoint body");
  });
  const mounted = await dom.mount(
    account({
      isLoading: false,
      isAuthenticated: true,
      user: verifiedUser,
      getAccessTokenSilently: tokenFailure,
      loginWithRedirect: async () => {
        throw new Error("private redirect detail");
      },
    }),
  );
  await flush();
  assert.match(
    mounted.container.querySelector('[role="alert"]')!.textContent!,
    /preferences couldn't be loaded/,
  );
  assert.doesNotMatch(
    mounted.container.textContent!,
    /private token endpoint body/,
  );
  await click(button(mounted.container, /Connect email preferences/));
  assert.equal(
    mounted.container.querySelector('[role="alert"]')!.textContent,
    "Email preferences could not connect. Your sign-in account is still available.",
  );
  assert.match(mounted.container.textContent!, /Current status: Unavailable/);
});

test("preference HTTP failure stays on the account page with a retry path", async (t) => {
  const dom = componentDom(t);
  await loadAccount(t);
  const requests = t.mock.method(globalThis, "fetch", async () =>
    json({ error: "Preferences are temporarily unavailable." }, 503),
  );
  const failed = await dom.mount(
    account({
      isLoading: false,
      isAuthenticated: true,
      user: verifiedUser,
      getAccessTokenSilently: async () => "fixture",
    }),
  );
  await flush();
  assert.match(
    failed.container.querySelector('[role="alert"]')!.textContent!,
    /temporarily unavailable/,
  );
  assert.equal(requests.mock.callCount(), 1);
});
