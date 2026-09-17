import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";

import { ConnectionsPage } from "@/features/integrations/components/connections-page";
import { api } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ api: vi.fn() }));
const apiMock = vi.mocked(api);

const base = {
  platforms: ["linkedin"],
  source_defaults: {
    gmail: { max_items: 5, lookback_hours: 24, scheduled_enabled: false, label_ids: ["INBOX"] },
    google_drive: { max_items: 4, lookback_hours: 24, scheduled_enabled: false, folder_id: "", folder_name: "" },
  },
  lookback_choices: [24, 48, 168],
  source_max_items: 20,
};

beforeEach(() => apiMock.mockReset());

test("shows Gmail and Drive as independent opt-in sources", async () => {
  apiMock.mockResolvedValueOnce({ ...base, connections: [] });

  render(<ConnectionsPage />);

  expect(await screen.findByRole("button", { name: "Connect Gmail" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Connect Google Drive" })).toBeDefined();
});

test("loads Gmail labels and saves bounded scheduled settings", async () => {
  apiMock.mockImplementation(async (path) => {
    if (path === "/connections") return { ...base, connections: [{ provider: "gmail", scopes: ["gmail.readonly"], expires_at: "2026-12-01T00:00:00Z", status: "active", meta: { account: "user@example.com", policy: base.source_defaults.gmail } }] };
    if (path === "/connections/gmail/labels") return { labels: [{ id: "INBOX", name: "Inbox" }, { id: "Label_1", name: "Launches" }] };
    return { policy: base.source_defaults.gmail };
  });
  const user = userEvent.setup();
  render(<ConnectionsPage />);

  const scheduled = await screen.findByRole("checkbox", { name: "Allow this source in scheduled runs" });
  await user.click(scheduled);
  await user.click(screen.getByRole("button", { name: "Save source settings" }));

  await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/connections/gmail/settings", expect.objectContaining({ method: "PUT" })));
  const saveCall = apiMock.mock.calls.find(([path]) => path === "/connections/gmail/settings");
  expect(JSON.parse(String(saveCall?.[1]?.body)).scheduled_enabled).toBe(true);
});
