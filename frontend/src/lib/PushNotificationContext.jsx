import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useMemo, useState } from "react";

import ProductRunDetailModal from "../components/ProductRunDetailModal.jsx";
import ProductSyncSummaryModal from "../components/ProductSyncSummaryModal.jsx";

// App-wide owner of the push-run result modals (summary + detail). Mounted once
// (AppLayout). A push is now reported by email, so there is no background polling
// and no auto-pop on completion — the user opens a run's result on demand from
// the notification bell (which fetches lazily). This provider just exposes
// ``openRun`` (open a run's summary modal) and ``notifyStarted`` (refresh the bell
// right after a push is triggered) and renders the two modals.

const PushNotificationContext = createContext({
  openRun: () => {},
  notifyStarted: () => {},
});

export const usePushNotifications = () => useContext(PushNotificationContext);

export function PushNotificationProvider({ children }) {
  const qc = useQueryClient();
  const [summaryRunId, setSummaryRunId] = useState(null);
  const [detailRunId, setDetailRunId] = useState(null);

  const value = useMemo(
    () => ({
      // Open a run's summary modal on demand (the bell uses this).
      openRun: (runId) => setSummaryRunId(runId),
      // Called right after a push is triggered so the new RUNNING notification
      // (and the bell badge) shows up on the next lazy fetch instead of waiting.
      notifyStarted: () => {
        qc.invalidateQueries({ queryKey: ["notifications"] });
      },
    }),
    [qc],
  );

  return (
    <PushNotificationContext.Provider value={value}>
      {children}
      <ProductSyncSummaryModal
        runId={summaryRunId}
        open={summaryRunId != null}
        onClose={() => setSummaryRunId(null)}
        onViewDetail={() => {
          setDetailRunId(summaryRunId);
          setSummaryRunId(null);
        }}
      />
      <ProductRunDetailModal
        runId={detailRunId}
        open={detailRunId != null}
        onClose={() => setDetailRunId(null)}
      />
    </PushNotificationContext.Provider>
  );
}
