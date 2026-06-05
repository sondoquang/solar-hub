import { Button, Checkbox, Divider, Form, Input } from "antd";
import { BarChart2, Lock, ShieldCheck, TrendingUp, User } from "lucide-react";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";
import { useNavigate, useLocation } from "react-router-dom";

import { useAuth } from "../lib/AuthContext.jsx";

const FEATURES = [
  {
    icon: TrendingUp,
    color: "bg-blue-500/20 text-blue-300",
    title: "Giám sát thời gian thực",
    desc: "Theo dõi hiệu suất hệ thống 24/7",
  },
  {
    icon: ShieldCheck,
    color: "bg-green-500/20 text-green-300",
    title: "Bảo mật tuyệt đối",
    desc: "Dữ liệu được bảo vệ an toàn và tin cậy",
  },
  {
    icon: BarChart2,
    color: "bg-amber-500/20 text-amber-300",
    title: "Báo cáo trực quan",
    desc: "Phân tích và báo cáo chi tiết, dễ hiểu",
  },
];

export default function Login() {
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  const from = location.state?.from?.pathname || "/";

  useEffect(() => {
    if (isAuthenticated) navigate(from, { replace: true });
  }, [isAuthenticated, navigate, from]);

  async function handleSubmit(values) {
    setLoading(true);
    try {
      await login({ username: values.username, password: values.password });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      toast.error(detail || "Tên đăng nhập hoặc mật khẩu không đúng.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen">
      {/* ── Left panel (50%) ──────────────────────────────────────── */}
      <div
        className="relative hidden w-1/2 flex-col overflow-hidden lg:flex"
        style={{
          backgroundImage: "url('/login-background.png')",
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      >
        {/* dark gradient overlay */}
        <div className="absolute inset-0 bg-gradient-to-br from-slate-900/75 via-slate-800/60 to-slate-900/50" />

        {/* Main content — vertically centered */}
        <div className="relative z-10 flex flex-1 flex-col justify-center px-10 py-10">
          {/* Logo — directly above headline */}
          <img
            src="/logo-admin-page.png"
            alt="Solar Hub"
            className="mb-8 w-56 h-auto object-contain object-left"
          />

          <h1 className="font-display text-4xl font-bold leading-tight text-white">
            Quản lý hệ thống
            <br />
            điện mặt trời hiệu quả
          </h1>
          <p className="mt-4 text-base text-white/75">
            Solar Hub giúp bạn giám sát, quản lý và tối ưu hiệu suất hệ thống
            điện mặt trời mọi lúc, mọi nơi.
          </p>

          {/* Feature cards */}
          <div className="mt-8 space-y-4">
            {FEATURES.map(({ icon: Icon, color, title, desc }) => (
              <div
                key={title}
                className="flex items-center gap-4 rounded-xl bg-white/10 p-4 backdrop-blur-sm"
              >
                <span
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${color}`}
                >
                  <Icon size={20} />
                </span>
                <div>
                  <p className="font-semibold text-white">{title}</p>
                  <p className="text-sm text-white/65">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Right panel (50%) ─────────────────────────────────────── */}
      <div className="flex w-full flex-col items-center justify-between bg-white px-8 py-10 lg:w-1/2">
        <div /> {/* top spacer */}

        <div className="w-full max-w-sm">
          {/* Mobile logo — directly above heading */}
          <img
            src="/logo-admin-page.png"
            alt="Solar Hub"
            className="mb-6 h-10 object-contain lg:hidden"
          />

          <h2 className="text-center font-display text-2xl font-bold text-ink">
            Đăng nhập hệ thống
          </h2>
          <p className="mt-1.5 text-center text-sm text-muted">
            Vui lòng nhập thông tin để tiếp tục
          </p>

          <Form
            form={form}
            layout="vertical"
            onFinish={handleSubmit}
            className="mt-8"
            requiredMark={false}
          >
            <Form.Item
              label="Email hoặc tên đăng nhập"
              name="username"
              rules={[{ required: true, message: "Vui lòng nhập tên đăng nhập" }]}
            >
              <Input
                prefix={<User size={15} className="text-slate-400" />}
                placeholder="Nhập email hoặc tên đăng nhập"
                size="large"
              />
            </Form.Item>

            <Form.Item
              label="Mật khẩu"
              name="password"
              rules={[{ required: true, message: "Vui lòng nhập mật khẩu" }]}
            >
              <Input.Password
                prefix={<Lock size={15} className="text-slate-400" />}
                placeholder="Nhập mật khẩu"
                size="large"
              />
            </Form.Item>

            <Form.Item name="remember" valuePropName="checked" noStyle>
              <div className="flex items-center justify-between">
                <Checkbox>
                  <span className="text-sm text-slate-600">Ghi nhớ đăng nhập</span>
                </Checkbox>
                <Button type="link" size="small" className="px-0 font-medium">
                  Quên mật khẩu?
                </Button>
              </div>
            </Form.Item>

            <Form.Item className="mt-6">
              <Button
                type="primary"
                htmlType="submit"
                size="large"
                block
                loading={loading}
                style={{ background: "var(--color-brand)", borderColor: "var(--color-brand)" }}
              >
                {loading ? "Đang đăng nhập…" : "Đăng nhập"}
              </Button>
            </Form.Item>
          </Form>

          <Divider plain>
            <span className="text-xs text-muted">hoặc đăng nhập với</span>
          </Divider>

          <Button
            size="large"
            block
            icon={
              <svg viewBox="0 0 48 48" className="h-4 w-4">
                <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
                <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.31-8.16 2.31-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
              </svg>
            }
            className="flex items-center justify-center gap-2 border-slate-200 text-slate-700 hover:border-slate-300 hover:bg-slate-50"
            onClick={() => toast("Tính năng đăng nhập Google chưa khả dụng.", { icon: "ℹ️" })}
          >
            Đăng nhập với Google
          </Button>
        </div>

        <p className="text-xs text-muted">
          © 2024 SolarPower. All rights reserved.
        </p>
      </div>
    </div>
  );
}
