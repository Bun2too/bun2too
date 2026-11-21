import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { componentDom, publicEnv, flush } from "./helpers/component-dom";

test("AuthProvider leaves public content available when browser Auth0 configuration is absent", async (t) => {
  const dom = componentDom(t);
  publicEnv(t, {
    NEXT_PUBLIC_AUTH0_DOMAIN: undefined,
    NEXT_PUBLIC_AUTH0_CLIENT_ID: undefined,
    NEXT_PUBLIC_AUTH0_AUDIENCE: undefined,
  });
  const { default: AuthProvider } =
    await import("../src/components/AuthProvider");
  const mounted = await dom.mount(
    createElement(
      AuthProvider,
      null,
      createElement("main", null, "Public content fixture"),
    ),
  );
  await flush();
  assert.equal(
    mounted.container.querySelector("main")!.textContent,
    "Public content fixture",
  );
  assert.equal(mounted.container.querySelector("[data-auth0-provider]"), null);
});
