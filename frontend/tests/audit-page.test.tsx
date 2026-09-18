import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";

import { AuditPage } from "@/features/audit/components/audit-page";
import { api } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ api: vi.fn() }));
const apiMock = vi.mocked(api);

beforeEach(() => apiMock.mockReset());

test("shows ten audit events per page and navigates to the next page", async () => {
  apiMock.mockResolvedValue({
    ledger: Array.from({ length: 11 }, (_, index) => ({
      id: index + 1,
      ts: `2026-09-${String(index + 1).padStart(2, "0")}T10:00:00Z`,
      provider: "github",
      action: "read",
      details: `Audit event ${index + 1}`,
    })),
  });
  const user = userEvent.setup();
  render(<AuditPage />);

  expect(await screen.findByText("Audit event 1")).toBeDefined();
  expect(screen.queryByText("Audit event 11")).toBeNull();
  expect(screen.getByText("Showing 1–10 of 11")).toBeDefined();

  await user.click(screen.getByRole("button", { name: "Next page" }));

  expect(screen.getByText("Audit event 11")).toBeDefined();
  expect(screen.queryByText("Audit event 1")).toBeNull();
  expect(screen.getByText("Showing 11–11 of 11")).toBeDefined();
});
