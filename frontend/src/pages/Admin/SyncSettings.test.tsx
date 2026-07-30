import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useSyncSettings } from "../../api/hooks/useSyncSettings";
import { useUpdateSyncSettings } from "../../api/hooks/useUpdateSyncSettings";
import { useTriggerSyncNow } from "../../api/hooks/useTriggerSyncNow";
import { SyncSettings } from "./SyncSettings";

vi.mock("../../api/hooks/useSyncSettings");
vi.mock("../../api/hooks/useUpdateSyncSettings");
vi.mock("../../api/hooks/useTriggerSyncNow");

describe("SyncSettings", () => {
  it("shows the current cron, schoolyear start, and last sync time", () => {
    vi.mocked(useSyncSettings).mockReturnValue({
      data: { sync_interval_cron: "*/30 * * * *", schuljahr_start_cache: "2025-09-15", letzter_sync_am: "2026-07-29T06:00:00Z" },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    vi.mocked(useUpdateSyncSettings).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);
    vi.mocked(useTriggerSyncNow).mockReturnValue({ mutate: vi.fn(), isPending: false, isSuccess: false, error: null } as any);

    render(<SyncSettings />);
    expect(screen.getByDisplayValue("*/30 * * * *")).toBeInTheDocument();
    expect(screen.getByText(/2025-09-15/)).toBeInTheDocument();
  });

  it("submits the edited cron expression", async () => {
    const updateMutate = vi.fn();
    vi.mocked(useSyncSettings).mockReturnValue({
      data: { sync_interval_cron: "*/30 * * * *", schuljahr_start_cache: null, letzter_sync_am: null },
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateSyncSettings).mockReturnValue({ mutate: updateMutate, isPending: false, error: null } as any);
    vi.mocked(useTriggerSyncNow).mockReturnValue({ mutate: vi.fn(), isPending: false, isSuccess: false, error: null } as any);

    render(<SyncSettings />);
    const input = screen.getByLabelText("Sync-Intervall");
    await userEvent.clear(input);
    await userEvent.type(input, "0 * * * *");
    await userEvent.click(screen.getByText("Speichern"));

    expect(updateMutate).toHaveBeenCalledWith("0 * * * *");
  });
});
