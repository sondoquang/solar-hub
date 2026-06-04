import { useHealth } from "../api/health.js";
import ErrorState from "../components/ErrorState.jsx";
import Loading from "../components/Loading.jsx";

// Scaffold page: proves the frontend reaches the backend end-to-end.
export default function Dashboard() {
  const { data, isLoading, isError, refetch } = useHealth();

  if (isLoading) return <Loading />;
  if (isError) return <ErrorState message="Không kết nối được backend" onRetry={refetch} />;

  return (
    <section>
      <h1 className="mb-4 font-display text-2xl font-bold">Dashboard</h1>
      <p className="mb-2 text-muted">Trạng thái backend:</p>
      <pre className="rounded bg-white p-4 shadow-card">{JSON.stringify(data, null, 2)}</pre>
    </section>
  );
}
