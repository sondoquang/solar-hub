import { lazy, Suspense } from "react";
import { Navigate, Outlet, createBrowserRouter, useLocation } from "react-router-dom";
import { Toaster } from "react-hot-toast";

import AppLayout from "./components/AppLayout.jsx";
import Loading from "./components/Loading.jsx";
import { AuthProvider, useAuth } from "./lib/AuthContext.jsx";

const Dashboard = lazy(() => import("./pages/Dashboard.jsx"));
const Orders = lazy(() => import("./pages/Orders.jsx"));
const Products = lazy(() => import("./pages/Products.jsx"));
const Sites = lazy(() => import("./pages/Sites.jsx"));
const Hostings = lazy(() => import("./pages/Hostings.jsx"));
const Login = lazy(() => import("./pages/Login.jsx"));

const wrap = (Page) => (
  <Suspense fallback={<Loading />}>
    <Page />
  </Suspense>
);

// Root layout: provides AuthContext to every route (needs to be inside the
// router so AuthProvider can call useNavigate for logout).
function RootLayout() {
  return (
    <AuthProvider>
      <Toaster position="top-right" />
      <Outlet />
    </AuthProvider>
  );
}

function RequireAuth({ children }) {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) return <Loading />;
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return children;
}

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      {
        path: "/",
        element: (
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        ),
        children: [
          { index: true, element: wrap(Dashboard) },
          { path: "orders", element: wrap(Orders) },
          { path: "products", element: wrap(Products) },
          { path: "sites", element: wrap(Sites) },
          { path: "hostings", element: wrap(Hostings) },
        ],
      },
      { path: "/login", element: wrap(Login) },
    ],
  },
]);
