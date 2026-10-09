import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { useSyncSettings } from "../../api/hooks/useSyncSettings";
import { useSyncStatus } from "../../api/hooks/useSyncStatus";
import { useUpdateSyncSettings } from "../../api/hooks/useUpdateSyncSettings";
import { useTriggerSyncNow } from "../../api/hooks/useTriggerSyncNow";
import type { SyncStatus } from "../../api/types";
import { formatUhrzeitDe } from "../../utils/datum";
import { SyncSettings } from "./SyncSettings";

vi.mock("../../api/hooks/useSyncSettings");
vi.mock("../../api/hooks/useSyncStatus");
vi.mock("../../api/hooks/useUpdateSyncSettings");
vi.mock("../../api/hooks/useTriggerSyncNow");

const SETTINGS = {
  sync_interval_cron: "*/30 * * * *",
  schuljahr_start_cache: "2025-09-15",
  letzter_sync_am: "2026-07-29T06:00:00Z",
  aktuelles_schuljahr: null,
};
const IDLE: SyncStatus = { laeuft: false, aktueller_lauf: null, letzter_lauf: null };
const START = "2026-10-09T07:05:00Z";

function mockHooks(opts: {
  status?: SyncStatus | undefined;
  trigger?: Record<string, unknown>;
  update?: Record<string, unknown>;
} = {}) {
  vi.mocked(useSyncSettings).mockReturnValue({ data: SETTINGS, isLoading: false, isError: false } as any);
  vi.mocked(useSyncStatus).mockReturnValue({ data: "status" in opts ? opts.status : IDLE } as any);
  vi.mocked(useUpdateSyncSettings).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null, ...opts.update } as any);
  vi.mocked(useTriggerSyncNow).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null, ...opts.trigger } as any);
}

describe("SyncSettings", () => {
  beforeEach(() => vi.resetAllMocks());

  it("shows the current cron, schoolyear start, and last sync time", () => {
    mockHooks();
    render(<SyncSettings />);
    expect(screen.getByDisplayValue("*/30 * * * *")).toBeInTheDocument();
    expect(screen.getByText(/2025-09-15/)).toBeInTheDocument();
  });

  it("submits the edited cron expression", async () => {
    const updateMutate = vi.fn();
    mockHooks({ update: { mutate: updateMutate } });
    render(<SyncSettings />);
    const input = screen.getByLabelText("Sync-Intervall");
    await userEvent.clear(input);
    await userEvent.type(input, "0 * * * *");
    await userEvent.click(screen.getByText("Speichern"));
    expect(updateMutate).toHaveBeenCalledWith("0 * * * *");
  });

  it("shows the schoolyear the sync is currently using", () => {
    vi.mocked(useSyncSettings).mockReturnValue({
      data: { ...SETTINGS, aktuelles_schuljahr: { id: 28, name: "2025/2026" } },
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useSyncStatus).mockReturnValue({ data: IDLE } as any);
    vi.mocked(useUpdateSyncSettings).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);
    vi.mocked(useTriggerSyncNow).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);
    render(<SyncSettings />);
    expect(screen.getByText(/2025\/2026/)).toBeInTheDocument();
  });

  it("starts a sync on button click", async () => {
    const triggerMutate = vi.fn();
    mockHooks({ trigger: { mutate: triggerMutate } });
    render(<SyncSettings />);
    const button = screen.getByRole("button", { name: "Sync jetzt ausführen" });
    expect(button).toBeEnabled();
    await userEvent.click(button);
    expect(triggerMutate).toHaveBeenCalledTimes(1);
  });

  it("disables the button while the start request is in flight", () => {
    mockHooks({ trigger: { isPending: true } });
    render(<SyncSettings />);
    expect(screen.getByRole("button", { name: "Sync jetzt ausführen" })).toBeDisabled();
  });

  it("shows the running state with start time and phase and disables the button", () => {
    mockHooks({
      status: {
        laeuft: true,
        aktueller_lauf: { id: 3, gestartet_am: START, phase: "Fehlzeiten", ausgeloest_von: "manuell" },
        letzter_lauf: null,
      },
    });
    render(<SyncSettings />);
    expect(screen.getByText(`Sync läuft seit ${formatUhrzeitDe(START)} (Phase: Fehlzeiten)`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync jetzt ausführen" })).toBeDisabled();
  });

  it("shows a running sync without a phase yet", () => {
    mockHooks({
      status: {
        laeuft: true,
        aktueller_lauf: { id: 3, gestartet_am: START, phase: null, ausgeloest_von: "zeitplan" },
        letzter_lauf: null,
      },
    });
    render(<SyncSettings />);
    expect(screen.getByText(`Sync läuft seit ${formatUhrzeitDe(START)}`)).toBeInTheDocument();
  });

  it("shows a successful last run with time and trigger", () => {
    mockHooks({
      status: {
        laeuft: false,
        aktueller_lauf: null,
        letzter_lauf: { id: 2, status: "ok", gestartet_am: START, beendet_am: "2026-10-09T07:09:00Z", ausgeloest_von: "manuell", fehler_kurz: null },
      },
    });
    render(<SyncSettings />);
    expect(screen.getByText(`Letzter Sync-Lauf: ok (${formatUhrzeitDe(START)}, manuell)`)).toBeInTheDocument();
    expect(screen.queryByText(/Server-Log/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync jetzt ausführen" })).toBeEnabled();
  });

  it("shows a failed last run with the short error and a hint to the server log", () => {
    mockHooks({
      status: {
        laeuft: false,
        aktueller_lauf: null,
        letzter_lauf: { id: 2, status: "fehler", gestartet_am: START, beendet_am: START, ausgeloest_von: "zeitplan", fehler_kurz: "WebUntisError: Login fehlgeschlagen" },
      },
    });
    render(<SyncSettings />);
    expect(screen.getByText(`Letzter Sync-Lauf: Fehler (${formatUhrzeitDe(START)}, Zeitplan)`)).toBeInTheDocument();
    expect(screen.getByText(/WebUntisError: Login fehlgeschlagen/)).toBeInTheDocument();
    expect(screen.getByText(/Server-Log/)).toBeInTheDocument();
  });

  it("shows an aborted last run", () => {
    mockHooks({
      status: {
        laeuft: false,
        aktueller_lauf: null,
        letzter_lauf: { id: 2, status: "abgebrochen", gestartet_am: START, beendet_am: START, ausgeloest_von: "manuell", fehler_kurz: null },
      },
    });
    render(<SyncSettings />);
    expect(screen.getByText(`Letzter Sync-Lauf: abgebrochen (${formatUhrzeitDe(START)}, manuell)`)).toBeInTheDocument();
  });

  it("shows no run info before the first status response", () => {
    mockHooks({ status: undefined });
    render(<SyncSettings />);
    expect(screen.queryByText(/Sync läuft/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Letzter Sync-Lauf/)).not.toBeInTheDocument();
  });

  it("shows 'Ein Sync läuft bereits' on 409", () => {
    mockHooks({ trigger: { error: new ApiError(409, "conflict") } });
    render(<SyncSettings />);
    expect(screen.getByText("Ein Sync läuft bereits.")).toBeInTheDocument();
  });

  it("shows a generic start error for other failures", () => {
    mockHooks({ trigger: { error: new ApiError(502, "bad gateway") } });
    render(<SyncSettings />);
    expect(screen.getByText("Sync konnte nicht gestartet werden.")).toBeInTheDocument();
  });
});
