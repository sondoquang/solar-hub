import EmptyState from "../components/EmptyState.jsx";

export default function Orders() {
  return (
    <section>
      <h1 className="mb-4 font-display text-2xl font-bold">Đơn hàng</h1>
      <EmptyState title="Chưa có đơn hàng" hint="Tính năng gom đơn sẽ được bổ sung." />
    </section>
  );
}
