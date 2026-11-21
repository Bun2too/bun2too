import { context, propagation, trace } from "@opentelemetry/api";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activeTraceId,
  annotateActiveSpan,
  RELAY_ATTR,
  startTelemetry,
  withTraceHeaders,
} from "../src/index.js";

const SPAN = trace.wrapSpanContext({
  traceId: "0af7651916cd43dd8448eb211c80319c",
  spanId: "b7ad6b7169203331",
  traceFlags: 1,
});

afterEach(() => {
  vi.unstubAllEnvs();
  propagation.disable();
});

describe("telemetry", () => {
  it("uses stable attribute names for tenant, case and channel", () => {
    expect(RELAY_ATTR).toEqual({
      tenant: "relay.tenant",
      caseId: "relay.case_id",
      channel: "relay.channel",
    });
  });

  it("starts nothing and stops cleanly when no OTLP endpoint is set", async () => {
    vi.stubEnv("OTEL_EXPORTER_OTLP_ENDPOINT", "");
    const stop = startTelemetry("relay-test");
    await expect(stop()).resolves.toBeUndefined();
  });

  it("starts and shuts down the SDK when an endpoint is set", async () => {
    vi.stubEnv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:9");
    const stop = startTelemetry("relay-test", "9.9.9");
    await expect(stop()).resolves.toBeUndefined();
  });

  it("reports no trace id and annotates nothing outside a span", () => {
    expect(activeTraceId()).toBeUndefined();
    expect(() => annotateActiveSpan({ [RELAY_ATTR.tenant]: "acme" })).not.toThrow();
  });

  it("reads the active span's trace id and sets attributes on it", () => {
    const setAttributes = vi.spyOn(SPAN, "setAttributes");
    context.with(trace.setSpan(context.active(), SPAN), () => {
      expect(activeTraceId()).toBe("0af7651916cd43dd8448eb211c80319c");
      annotateActiveSpan({ [RELAY_ATTR.tenant]: "acme" });
    });
    expect(setAttributes).toHaveBeenCalledWith({ "relay.tenant": "acme" });
  });

  it("injects W3C trace headers into outgoing calls", () => {
    // A minimal stand-in for the SDK's W3C propagator: the test checks the wiring.
    propagation.setGlobalPropagator({
      inject: (ctx, carrier: Record<string, string>) => {
        const span = trace.getSpanContext(ctx);
        if (span) carrier.traceparent = `00-${span.traceId}-${span.spanId}-01`;
      },
      extract: (ctx) => ctx,
      fields: () => ["traceparent"],
    });
    const headers = context.with(trace.setSpan(context.active(), SPAN), () =>
      withTraceHeaders({ "content-type": "application/json" }),
    );
    expect(headers).toEqual({
      "content-type": "application/json",
      traceparent: "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
    });
  });
});
