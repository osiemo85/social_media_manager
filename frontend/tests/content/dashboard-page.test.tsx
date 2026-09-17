import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";

import { DashboardPage } from "@/features/content/components/dashboard-page";
import { api } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ api: vi.fn() }));
const apiMock = vi.mocked(api);

beforeEach(() => apiMock.mockReset());

test("manual pipeline run sends the visible Gmail bounds", async () => {
  apiMock.mockImplementation(async (path) => {
    if (path === "/dashboard") return { pending: 0, published: 0, unused: 0, mode: "review", schedule: 0, recent: [], connections: [{ provider: "gmail", status: "active", meta: { policy: { max_items: 5, lookback_hours: 24 } } }] };
    return { ingested: { gmail: 0 }, outcome: null };
  });
  const user = userEvent.setup();
  render(<DashboardPage />);

  expect((await screen.findByRole("checkbox", { name: "gmail" }) as HTMLInputElement).checked).toBe(true);
  await user.click(screen.getByRole("button", { name: "Run pipeline now" }));

  await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/pipeline/run", expect.objectContaining({ method: "POST" })));
  const runCall = apiMock.mock.calls.find(([path]) => path === "/pipeline/run");
  expect(JSON.parse(String(runCall?.[1]?.body))).toEqual({ sources: { gmail: { enabled: true, max_items: 5, lookback_hours: 24 } } });
});
