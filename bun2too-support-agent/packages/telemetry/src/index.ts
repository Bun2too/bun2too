import { context, propagation, trace } from "@opentelemetry/api";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { HttpInstrumentation } from "@opentelemetry/instrumentation-http";
import { UndiciInstrumentation } from "@opentelemetry/instrumentation-undici";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { NodeSDK } from "@opentelemetry/sdk-node";
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from "@opentelemetry/semantic-conventions";

export const RELAY_ATTR = {
  tenant: "relay.tenant",
  caseId: "relay.case_id",
  channel: "relay.channel",
} as const;

export function startTelemetry(serviceName: string, version = "0.1.0"): () => Promise<void> {
  if (!process.env.OTEL_EXPORTER_OTLP_ENDPOINT) return async () => {};
  const sdk = new NodeSDK({
    resource: resourceFromAttributes({
      [ATTR_SERVICE_NAME]: serviceName,
      [ATTR_SERVICE_VERSION]: version,
    }),
    traceExporter: new OTLPTraceExporter(),
    instrumentations: [new HttpInstrumentation(), new UndiciInstrumentation()],
  });
  sdk.start();
  return () => sdk.shutdown();
}

export function annotateActiveSpan(attributes: Record<string, string>): void {
  trace.getActiveSpan()?.setAttributes(attributes);
}

export function activeTraceId(): string | undefined {
  return trace.getActiveSpan()?.spanContext().traceId;
}

export function withTraceHeaders(headers: Record<string, string>): Record<string, string> {
  propagation.inject(context.active(), headers);
  return headers;
}
