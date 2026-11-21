import assert from "node:assert/strict";
import { test } from "node:test";
import { registerHooks } from "node:module";
import { renderToStaticMarkup } from "react-dom/server";
import { publicEnv } from "./helpers/component-dom";

test("CMS newsletter block falls back to local published seed content in both placements", async (t) => {
  const hooks = registerHooks({
    resolve(specifier, context, nextResolve) {
      if (specifier === "server-only")
        return {
          url: new URL("./helpers/server-only.mjs", import.meta.url).href,
          shortCircuit: true,
        };
      return nextResolve(specifier, context);
    },
  });
  t.after(() => hooks.deregister());
  publicEnv(t, { CONTENTFUL_ENABLED: "false" });
  const { default: CmsNewsletter } =
    await import("../src/components/CmsNewsletter");
  const general = renderToStaticMarkup(
    await CmsNewsletter({ insights: false }),
  );
  const insights = renderToStaticMarkup(
    await CmsNewsletter({ insights: true }),
  );
  assert.match(general, /id="subscribe"/);
  assert.match(insights, /id="subscribe"/);
  assert.match(general, /Your email address/);
  assert.match(insights, /Your email address/);
  assert.match(general, /Customer technology/);
  assert.match(insights, /AI &amp; automation/);
});
