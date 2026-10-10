import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import type { JobSummary, Message } from "../api/client";
import MessageBubble from "../components/MessageBubble";
import { verdictLabel } from "../lib/verdicts";
import { mergeEvents, useStore } from "../state/store";

const msg: Message = {
  id: "m1", conversation_id: "c1", seq: 1, role: "user", kind: "text",
  text: "Any user-written claim the developer has never seen.", created_at: new Date().toISOString(),
  attachment: null, latest_job: null,
};

const job = (over: Partial<JobSummary>): JobSummary => ({
  id: "j1", message_id: "m1", status: "running", attempt: 1, language: "en", overall_verdict: null,
  evidence_strength: null, error_code: null, error_message: null, created_at: new Date().toISOString(),
  started_at: null, finished_at: null, ...over,
});

beforeEach(() => useStore.setState({ jobs: {}, msgJob: {}, verifyPending: {} }));

describe("MessageBubble", () => {
  it("shows a Verify action for an unchecked message", () => {
    render(<MessageBubble message={msg} />);
    expect(screen.getByText(msg.text)).toBeInTheDocument();
    expect(screen.getByTestId("verify-button")).toHaveTextContent("Verify");
  });

  it("shows real stage progress, not a verdict, while running", () => {
    useStore.setState({
      jobs: { j1: { summary: job({}), events: [
        { id: 1, seq: 1, job_id: "j1", kind: "stage", stage: "received", status: "completed", detail: null, at: "" },
        { id: 2, seq: 2, job_id: "j1", kind: "stage", stage: "searching_sources", status: "started", detail: null, at: "" },
      ] } },
      msgJob: { m1: "j1" },
    });
    render(<MessageBubble message={msg} />);
    expect(screen.getByTestId("verify-progress")).toHaveTextContent("Searching sources");
    expect(screen.queryByTestId("verify-result")).toBeNull();
  });

  it("a failed job shows an error and Retry, never a verdict", () => {
    useStore.setState({ jobs: { j1: { summary: job({ status: "failed", error_code: "provider_not_configured" }), events: [] } }, msgJob: { m1: "j1" } });
    render(<MessageBubble message={msg} />);
    expect(screen.getByTestId("verify-failed")).toHaveTextContent("Retry");
    expect(screen.queryByTestId("verify-result")).toBeNull();
  });

  it("ignores a job that belongs to another message", () => {
    useStore.setState({ jobs: { j1: { summary: job({ message_id: "other", status: "completed", overall_verdict: "false" }), events: [] } }, msgJob: { m1: "j1" } });
    render(<MessageBubble message={msg} />);
    expect(screen.getByTestId("verify-button")).toBeInTheDocument();
  });
});

describe("helpers", () => {
  it("merges and de-duplicates events in sequence order", () => {
    const e = (id: number) => ({ id, seq: id, job_id: "j", kind: "stage", stage: "x", status: "started", detail: null, at: "" });
    expect(mergeEvents([e(2), e(1)], [e(2), e(3)]).map((x) => x.id)).toEqual([1, 2, 3]);
  });

  it("labels verdicts per language", () => {
    expect(verdictLabel("insufficient_evidence", "en")).toBe("Insufficient evidence");
    expect(verdictLabel("false", "mr")).toBe("खोटे");
  });
});
