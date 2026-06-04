import EmptyState from "../components/EmptyState.jsx";

export default function Products() {
  return (
    <section>
      <h1 className="mb-4 font-display text-2xl font-bold">Sản phẩm</h1>
      <EmptyState title="Chưa có sản phẩm" hint="Master catalog sẽ được bổ sung." />
    </section>
  );
}
