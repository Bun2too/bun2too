import { expect, test } from "@playwright/test";
import { exportJWK, generateKeyPair, SignJWT } from "jose";

for (const permission of ["granted", "denied"] as const) {
  test(`sign-in succeeds independently of ${permission} preferences API access`, async ({
    page,
  }) => {
    const issuer = "https://website-test.example.auth0.com/";
    const origin = "http://localhost:3100";
    const { privateKey, publicKey } = await generateKeyPair("RS256");
    const nonces = new Map<string, string>();
    const preferencesRequests: URL[] = [];
    let apiCalls = 0;
    const cors = {
      "access-control-allow-origin": origin,
      "access-control-allow-headers": "*",
      "access-control-allow-methods": "GET, POST, OPTIONS",
    };
    await page.route(`${issuer}**`, async (route) => {
      const request = route.request(),
        url = new URL(request.url());
      if (request.method() === "OPTIONS")
        return route.fulfill({ status: 204, headers: cors });
      if (url.pathname === "/authorize") {
        const isPreferences = url.searchParams.has("audience");
        if (isPreferences) preferencesRequests.push(url);
        const code = isPreferences
          ? "fixture-preferences-code"
          : "fixture-login-code";
        nonces.set(code, url.searchParams.get("nonce")!);
        if (!isPreferences) {
          expect(url.searchParams.get("scope")).toBe("openid profile email");
          const callback = new URL(url.searchParams.get("redirect_uri")!);
          callback.searchParams.set("code", code);
          callback.searchParams.set("state", url.searchParams.get("state")!);
          return route.fulfill({
            status: 302,
            headers: { location: callback.href },
          });
        }
        expect(url.searchParams.get("audience")).toBe(
          "https://api.example.invalid",
        );
        expect(url.searchParams.get("scope")?.split(" ")).toContain(
          "manage:subscriptions",
        );
        const response =
          permission === "denied"
            ? {
                error: "invalid_request",
                error_description: "fixture-private-authorization-detail",
                state: url.searchParams.get("state"),
              }
            : { code, state: url.searchParams.get("state") };
        return route.fulfill({
          contentType: "text/html",
          body: `<script>parent.postMessage(${JSON.stringify({ type: "authorization_response", response })}, ${JSON.stringify(origin)})</script>`,
        });
      }
      if (url.pathname === "/oauth/token") {
        const body = request.postDataJSON();
        expect(body.grant_type).toBe("authorization_code");
        expect(body.code_verifier).toBeTruthy();
        const idToken = await new SignJWT({
          nonce: nonces.get(body.code),
          name: "Fixture account",
          email: "fixture@example.invalid",
          email_verified: true,
        })
          .setProtectedHeader({ alg: "RS256", kid: "fixture-key" })
          .setIssuer(issuer)
          .setAudience("test-spa-client-id")
          .setSubject("auth0|fixture-user")
          .setIssuedAt()
          .setExpirationTime("5m")
          .sign(privateKey);
        return route.fulfill({
          headers: cors,
          json: {
            access_token:
              body.code === "fixture-preferences-code"
                ? "fixture-preferences-access-token"
                : "fixture-identity-access-token",
            id_token: idToken,
            token_type: "Bearer",
            expires_in: 300,
          },
        });
      }
      if (url.pathname === "/.well-known/jwks.json")
        return route.fulfill({
          headers: cors,
          json: {
            keys: [
              {
                ...(await exportJWK(publicKey)),
                kid: "fixture-key",
                alg: "RS256",
                use: "sig",
              },
            ],
          },
        });
      return route.fulfill({ status: 404, headers: cors });
    });
    await page.route("**/api/preferences", async (route) => {
      apiCalls++;
      expect(route.request().headers().authorization).toBe(
        "Bearer fixture-preferences-access-token",
      );
      await route.fulfill({ json: { newsletter: null } });
    });
    await page.goto("/account");
    await page
      .locator(".account-card")
      .getByRole("button", { name: "Log in ↗", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Fixture account", exact: true }),
    ).toBeVisible();
    await expect.poll(() => preferencesRequests.length).toBe(1);
    await expect(
      page.getByText("Sign-in could not complete", { exact: false }),
    ).toHaveCount(0);
    if (permission === "denied") {
      await expect(
        page
          .getByRole("alert")
          .filter({ hasText: "You're signed in, but email preferences" }),
      ).toBeVisible();
      await expect(
        page.getByRole("button", {
          name: "Connect email preferences",
          exact: true,
        }),
      ).toBeVisible();
      await expect(page.locator("body")).not.toContainText(
        "fixture-private-authorization-detail",
      );
      expect(apiCalls).toBe(0);
      let reconnect: URL | undefined;
      await page.route(`${issuer}authorize**`, async (route) => {
        reconnect = new URL(route.request().url());
        await route.fulfill({
          contentType: "text/html",
          body: "<p>Preferences authorization captured</p>",
        });
      });
      await page
        .getByRole("button", { name: "Connect email preferences", exact: true })
        .click();
      await expect
        .poll(() => reconnect?.searchParams.get("audience"))
        .toBe("https://api.example.invalid");
      expect(reconnect?.searchParams.get("scope")?.split(" ")).toContain(
        "manage:subscriptions",
      );
      expect(reconnect?.searchParams.get("redirect_uri")).toBe(`${origin}/`);
      expect(reconnect?.searchParams.get("code_challenge_method")).toBe("S256");
    } else {
      await expect.poll(() => apiCalls).toBe(1);
      await expect(
        page.getByRole("button", { name: "Unsubscribe", exact: true }),
      ).toBeEnabled();
    }
  });
}
