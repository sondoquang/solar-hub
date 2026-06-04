import EmptyState from "../components/EmptyState.jsx";

export default function Sites() {
  return (
    <section>
      <h1 className="mb-4 font-display text-2xl font-bold">Website</h1>
      <EmptyState title="Chưa có website" hint="Đăng ký site sẽ được bổ sung." />
    </section>
  );
}
